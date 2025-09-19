import json
import math
import os
import re

import boto3
import requests
from timecode import Timecode

import aws_lambda.lambda_helpers.s3_helper as s3_helper
from aws_lambda.lambda_helpers.logging_helper import setup_logger
from aws_lambda.lambda_helpers.sqs_helper import send_message_to_return_queue

logger = setup_logger()

'''
This is a tool for correcting some common simple issues with delivered caption files:
-SCC files timed to 1-hour videos but which have vestigial timecode values at 00:58 or 00:59
-SCC files that start at 01:00:00:00 (but are otherwise correctly timed)
-SCC files timed to different frame rates than their video
-SCC files with incorrect drop-frame status

Data needed from Vidi/AWS:
1. VS job ID
2. Input SCC S3 URL
3. Output S3 URL
4. SCC start timecode (mi_text_time_code_first_frame)
5. Video start timecode (mi_time_code_first_frame)
6. Video frame rate (mi_time_code_frame_rate)

Additional values to be calculated:
-SCC/video drop frame status
-SCC frame rate

NOTE: Frame rate information is not included in SCC metadata.
SCC frame rate is calculated by looking at all frame values within the file and cross-checking
against possible frame rates.

Order of operations:
1. 58/59 TC removal
2. Hour shift
3. Frame rate conversion
4. Drop-frame conversion

Each operation returns a new file with a modified filename.
If multiple operations are required, the output file from the first operation will be used as the
input file for the next.
Logically, no more than two operations will ever be required. #1 and #2 are mutually exclusive
operations, as are #3 and #4.

Adjusted files are written to the output s3 URL.
If an adjusted SCC file is still bad, it should be examined manually and/or returned to sender.
'''
# GET ENVIRONMENT VARIABLES
# region
region_name = os.environ.get("regionName", "us-west-1")

# get the group name from the environment variables
group_name = os.environ.get("groupName", "fah")

# get the project name from the environment variables
project_name = os.environ.get("projectName", "mrss-translator")

# FUNCTIONS
# event/variable parsing functions
def build_event_dict(event):
    '''parse SQS payload'''

    # need this here for testing
    if isinstance(event, str):
        event = json.loads(event)

    event_fields = event['Records'][0]['body'].get('field',[])
    event_dict = {}
    for field in event_fields:
        key = field.get('key')
        value = field.get('value')

        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                # Keep the original string value if parsing fails
                pass

        # video frame rate conformance
        # SMPTE timecode maxes out at 30; higher frame rates use same TC as half-speed counterparts
        if key == 'mi_time_code_frame_rate':
            if value == '50':
                event_dict[key] = '25'
            elif value == '60':
                event_dict[key] = '30'
            elif value == '59.94' or re.match('29.9.*', str(value)):
                event_dict[key] = '29.97'
            elif re.match('23.9.*', str(value)):
                event_dict[key] = '23.976'
            else:
                event_dict[key] = value
        else:
            event_dict[key] = value

    # is everything present and good?
    validate(event_dict)

    # drop a big log
    logger.info(f'{event_dict['vs_job_id']} provided as vs job id.')
    logger.info(f'{event_dict['s3_url']} provided as input file path.')
    logger.info(f'{event_dict['output_s3_url']} provided as the output file path.')
    logger.info(f'{event_dict['mi_text_time_code_first_frame']} provided as scc starting timecode.')
    logger.info(f'{event_dict['mi_time_code_first_frame']} provided as video starting timecode.')
    logger.info(f'{event_dict['mi_time_code_frame_rate']} provided as video frame rate.')

    return event_dict

def validate(event_dict):
    '''Makes sure expected data is present / formatted correctly'''
    if 'vs_job_id' not in event_dict:
        raise ValueError('No vs_job_id found in event body.')
    if 's3_url' not in event_dict:
        raise ValueError('No input s3 url found in event body.')
    if 'output_s3_url' not in event_dict:
        raise ValueError('No output s3 url found in event body.')
    if 'mi_text_time_code_first_frame' not in event_dict:
        raise ValueError('No SCC starting timecode found in event body.')
    if 'mi_time_code_first_frame' not in event_dict:
        raise ValueError('No video starting timecode found in event body.')
    if 'mi_time_code_frame_rate' not in event_dict:
        raise ValueError('No video frame rate found in event body.')

    assert (
        event_dict['s3_url'][-3:].lower() == 'scc'
        ), "Input file not an scc"
    assert (
        re.match(r'^\d{2}:\d{2}:\d{2}[:;]\d{2}$', event_dict['mi_time_code_first_frame'])
        ), "video mi_time_code_first_frame not formatted correctly"
    assert (
        re.match(r'^\d{2}:\d{2}:\d{2}[:;]\d{2}$',event_dict['mi_text_time_code_first_frame'])
        ), "scc mi_text_time_code_first_frame not formatted correctly"
    assert (
        event_dict['mi_time_code_frame_rate'] in ['23.976', '23.98', '24', '25', '29.97', '30']
        ), "video mi_time_code_frame_rate an unexpected number"

    return True

def get_object_key(output_s3_url, s3_bucket, filename):
    # Extract the object key from the output_s3_url (remove s3://bucket-name/ prefix)
    if output_s3_url.startswith('s3://'):
        # Remove s3:// prefix and bucket name
        bucket_prefix = f"s3://{s3_bucket}/"
        if output_s3_url.startswith(bucket_prefix):
            object_key = output_s3_url[len(bucket_prefix):] + filename
        else:
            # Fallback: try to extract key from URL
            object_key = output_s3_url.replace('s3://', '').split('/', 1)[1] + filename
    else:
        object_key = output_s3_url + filename
    return object_key

# frame rate functions
def is_non_drop_frame(start_tc):
    '''Returns a Boolean'''
    ndf = ';' not in start_tc
    return ndf

def deduce_scc_frame_rate(ndf_scc, scc_lines):
    '''Calculates probable SCC frame rate'''
    # if semi-colon in timecode, frame rate is definitely 29.97 DF
    if not ndf_scc:
        scc_frame_rate = '29.97'

    # otherwise we calculate the highest frame number in the timecode
    else:
        max_frame = '00'
        for line in scc_lines:
            match = re.match(r'^(\d{2}:\d{2}:\d{2}[:;]\d{2})', line)
            if match:
                timecode = match.group()
                frame = timecode[-2:]
                max_frame = max(max_frame, frame)
        frame_rates = ['23.976', '25', '29.97']
        # 23.976/24 and 29.97/30 functionally have the same timecode, so fuck em

        # we want the lowest possible frame rate that is still a higher number than max_frame
        possible_frame_rates = []
        for rate in frame_rates:
            if max_frame < rate:
                possible_frame_rates.append(rate)
        scc_frame_rate = min(possible_frame_rates)

    logger.info(f'SCC frame rate is likely {scc_frame_rate}.')

    return scc_frame_rate

# scc/video attribute aggregation function
def set_up_attribute_objects(event_dict, scc_lines):
    '''
    Creates Timecode objects containing scc and video attributes and starting tc values
    '''

    # drop frame
    ndf_scc = is_non_drop_frame(event_dict['mi_text_time_code_first_frame'])
    ndf_video = is_non_drop_frame(event_dict['mi_time_code_first_frame'])

    # scc framerate
    scc_framerate = deduce_scc_frame_rate(ndf_scc, scc_lines)

    # put it all together
    scc_attributes = Timecode(
        framerate=scc_framerate,
        start_timecode=event_dict['mi_text_time_code_first_frame'],
        force_non_drop_frame=ndf_scc
        )
    video_attributes = Timecode(
        framerate=event_dict['mi_time_code_frame_rate'],
        start_timecode=event_dict['mi_time_code_first_frame'],
        force_non_drop_frame=ndf_video
        )

    return scc_attributes, video_attributes

# frame rate functions
def needs_frame_rate_convert(scc_frame_rate, video_frame_rate):
    '''Checks for need of frame-rate conversion'''
    return scc_frame_rate != video_frame_rate

def frame_rate_suffix(scc_attributes, video_attributes):
    '''Prepares suffix for adjusted filename'''
    if scc_attributes.framerate == '29.97':
        old_frame_rate = '2997ndf' if scc_attributes.force_non_drop_frame else '2997df'
    else:
        old_frame_rate = scc_attributes.framerate.replace('.','')
    if video_attributes.framerate == '29.97':
        new_frame_rate = '2997ndf' if video_attributes.force_non_drop_frame else '2997df'
    else:
        new_frame_rate = video_attributes.framerate.replace('.','')
    return f'_{old_frame_rate}_to_{new_frame_rate}.scc'

def line_convert_frame_rate(line, scc_attributes, video_attributes, pre_delta, ratio):
    '''
    Conversion template (25fps SCC to 29.97 NDF video):
    scc_tc = Timecode(
            framerate='25',
            start_timecode=timecode
            ) - scc_delta
    ratio = video_frame_rate / scc_frame_rate
    new_frames = math.ceil(scc_tc.frames * ratio) # round up, never down
    video_scc = Timecode(
            framerate='29.97',
            frames=new_frames,
            force_non_drop_frame=True
            ) + video_delta
    '''
    # look for 1. timecode at start of line, 2. whitespace, 3. everything else (AKA dialogue)
    match = re.match(r'^(\d{2}:\d{2}:\d{2}[:;]\d{2})(\s+)(.*)', line)
    # if no timecode, throw it back unchanged
    if not match:
        return line.strip()
    # if timecode, store the line as a string
    timecode_string, space, dialogue = match.groups()

    # create a Timecode object from the timecode string
    try:
        tc_old = Timecode(
            framerate=scc_attributes.framerate,
            start_timecode=timecode_string,
            force_non_drop_frame=scc_attributes.force_non_drop_frame
            ) - pre_delta
        # Timecode objects evaluate to frames
        # If timecode == delta value, the above will = 0 frames and Timecode will throw an error
    except ValueError:
        tc_old = Timecode(
            framerate=scc_attributes.framerate,
            start_timecode='00:00:00:00',
            force_non_drop_frame=scc_attributes.force_non_drop_frame
            )

    # multiply the old frame count by the ratio to get the new frame count
    # round up with prejudice
    tc_new_frames = math.ceil(tc_old.frames * ratio)

    # use new frame count to create a new Timecode object
    tc_new = Timecode(
        framerate=video_attributes.framerate,
        frames=tc_new_frames,
        force_non_drop_frame=video_attributes.force_non_drop_frame
        ) + video_attributes

    # return modified line
    return f'{tc_new}{space}{dialogue}'

def colon_blow(scc_lines, scc_attributes, video_attributes):
    '''
    Converting SCC frame rate to match that of video

    Using calculated variables, convert every SCC timecode value from SCC frame rate to video frame
    rate (including drop-frame status).
    Video start timecode is used to create two delta Timecode objects: one using the SCC frame rate, 
    and a second using the video frame rate. SCC delta is subtracted from the SCC timecode value
    before conversion and video delta is added post-conversion.
    This is to ensure that the SCC timecode has the same starting point as the video (even though
    that starting point should be 0).
    '''
    # pre delta conforms to SCC frame rate
    # post delta as same attributes as video_attributes object
    # cast video_attributes as string to keep it from evaluating to frames and fucking up our count
    pre_delta = Timecode(
        framerate=scc_attributes.framerate,
        start_timecode=str(video_attributes),
        force_non_drop_frame=scc_attributes.force_non_drop_frame
        )

    # set up conversion ratio
    # ratio = new (video) frame rate / old (scc) frame rate
    if scc_attributes.framerate == '23.976':
        scc_frame_rate = 24000/1001
    elif scc_attributes.framerate == '29.97':
        scc_frame_rate = 30000/1001
    else:
        scc_frame_rate = scc_attributes.framerate
    ratio = float(video_attributes.framerate) / float(scc_frame_rate)

    # join the modified lines together as a string
    return '\n'.join(
        line_convert_frame_rate(line, scc_attributes, video_attributes, pre_delta, ratio)
            for line in scc_lines)

# DF/NDF functions
def needs_drop_frame_convert(ndf_scc, ndf_video):
    '''Checks for drop frame conversion need'''
    return ndf_scc != ndf_video

def line_convert_df_ndf(line, scc_attributes, video_attributes, pre_delta):
    '''
    Conversion template (DF SCC/NDF video):
    tc_df = Timecode(
        framerate='29.97',
        start_timecode=timecode,
        force_non_drop_frame=False
        ) - scc_delta
    tc_ndf = Timecode(
        framerate='29.97',
        frames=tc_df.frames,
        force_non_drop_frame=True
        ) + video_delta

    01:00:00;00 DF = 00:59:56:12 NDF
    01:00:00:00 NDF = 01:00:03;12 DF
    '''
    # look for 1. timecode at start of line, 2. whitespace, 3. everything else (AKA dialogue)
    match = re.match(r'^(\d{2}:\d{2}:\d{2}[:;]\d{2})(\s+)(.*)', line)
    # if no timecode, throw it back unchanged
    if not match:
        return line.strip()
    # if timecode, store the line as a string
    timecode_string, space, dialogue = match.groups()

    # create a Timecode object from the timecode string
    try:
        tc_old = Timecode(
            framerate='29.97',
            start_timecode=timecode_string,
            force_non_drop_frame=scc_attributes.force_non_drop_frame
            ) - pre_delta
    # If timecode and delta values are identical, Timecode will throw an error
    except ValueError:
        tc_old = Timecode(
            framerate='29.97',
            start_timecode='00:00:00:00',
            force_non_drop_frame=scc_attributes.force_non_drop_frame
            )

    # use tc_old frame count to create new Timecode object
    tc_new = Timecode(
        framerate='29.97',
        frames=tc_old.frames,
        force_non_drop_frame=video_attributes.force_non_drop_frame
        ) + video_attributes

    # return modified line
    return f'{tc_new}{space}{dialogue}'

def drop_kick(scc_lines, scc_attributes, video_attributes):
    '''
    Converting drop-frame status of SCC to match that of video

    Similar to frame rate conversion, but the conversion calculus is much simpler.

    Delta values are calculated, subtracted and re-added as they are during frame rate conversion.
    '''
    # build pre delta; post delta is video_attributes
    pre_delta = Timecode(
        framerate='29.97',
        start_timecode=str(video_attributes),
        force_non_drop_frame=scc_attributes.force_non_drop_frame)

    # join the modified lines together as a string
    return '\n'.join(
        line_convert_df_ndf(line, scc_attributes, video_attributes, pre_delta)
        for line in scc_lines)

# hour shift functions
def needs_hour_shift(scc_attributes):
    '''Checks for hour-shift need'''
    return scc_attributes >= '01:00:00:00'

def line_convert_hour_shift(line, scc_attributes, delta):
    '''Perform hour shift on individual lines'''
    match = re.match(r'^(\d{2}:\d{2}:\d{2}[:;]\d{2})(\s+)(.*)', line)
    if not match:
        return line.strip()
    timecode_string, space, dialogue = match.groups()

    # Timecode object from string
    tc_old = Timecode(
        framerate=scc_attributes.framerate,
        start_timecode=timecode_string,
        force_non_drop_frame=scc_attributes.force_non_drop_frame)

    # subtract video start time from TC
    # the math makes sense when you consider that '00:00:00:00' counts as 1 frame
    tc_new = Timecode(
        framerate=scc_attributes.framerate,
        frames=tc_old.frames-(delta.frames-1),
        force_non_drop_frame=scc_attributes.force_non_drop_frame)

    # return modified line
    return f'{tc_new}{space}{dialogue}'

def hour_shift(scc_lines, scc_attributes, video_attributes):
    '''
    Shifting ~1-hour SCC timecode to 0-hour
    (Criteria: both video and SCC starting timecode values are greater than 58 minutes;
    SCC starting value is empirically greater than the video)

    -Subtract the video's starting timecode value from each SCC timecode value
    '''
    # try to use the video's start time as a delta, otherwise use 1-hour
    if (video_attributes >= '01:00:00:00' and video_attributes <= scc_attributes):
        delta = Timecode(
            framerate=scc_attributes.framerate,
            start_timecode=str(video_attributes),
            force_non_drop_frame=scc_attributes.force_non_drop_frame)
    else:
        delta = Timecode(
            framerate=scc_attributes.framerate,
            start_timecode='01:00:00:00',
            force_non_drop_frame=scc_attributes.force_non_drop_frame)

    # join the modified lines together as a string
    return '\n'.join(line_convert_hour_shift(line, scc_attributes, delta) for line in scc_lines)

# 58/59 removal function
def needs_58_59_removal(scc_attributes, video_attributes):
    '''Checks for the need of 58/59 removal'''
    return (scc_attributes >= '00:58:00:00'
            and scc_attributes < '01:00:00:00'
            and video_attributes == '01:00:00:00')

def remove_58_59(scc_lines):
    '''
    Cleaning up 1-hour SCC files with extra bits of header at the 58th/59th minute

    -Discard all lines with timecode values starting at 00:58 or 00:59 and proceeding blank lines
    (SCC files are double-spaced)
    -Subtract 1 hour from each remaining timecode value using substring manipulation
    '''
# different logic than the others since we're discarding lines two at a time
    new_lines = []
    i = 0
    while i < len(scc_lines):
        line = scc_lines[i]

        # ignore all SCC lines with timecode starting with 00:58 or 00:59
        if line[:5] == '00:58' or line[:5] == '00:59':
            i += 1
            # SCC files are double-spaced, so we also need to ignore the following blank line
            if i < len(scc_lines) and scc_lines[i].strip() == '':
                i += 1
            continue

        # remove 1 hour from all remaining timecode values
        match = re.match(r'^(\d{2}:\d{2}:\d{2}[:;]\d{2})', line)
        if not match:
            new_lines.append(line.strip())
            i += 1
        else:
            # BRUTE FORCE
            shifted_line = f'{line[0]}{str(int(line[1]) - 1)}{line[2:]}'
            new_lines.append(shifted_line.strip())
            i += 1

    # return a joined string
    return '\n'.join(new_lines)

# aggregated correction function
def scc_correction(scc_filename, scc_lines, scc_attributes, video_attributes):
    '''runs scc data through each of the four checks'''

    # throw back the little ones
    # if SCC timecode starts at 2 hours or video starts anywhere over 1 hour, file is out of spec
    if scc_attributes >= '02:00:00:00' or video_attributes > '01:00:00:00':
        raise Exception('One or both sources have unacceptable timecode. Please check your files.')

    # if nothing is true, then why are we here?
    if (not needs_58_59_removal(scc_attributes, video_attributes)
        and not needs_hour_shift(scc_attributes)
        and not needs_frame_rate_convert(scc_attributes.framerate, video_attributes.framerate)
        and not needs_drop_frame_convert(scc_attributes.force_non_drop_frame,
                                         video_attributes.force_non_drop_frame)):
        raise Exception('SCC file passes checks. Either nothing is wrong with it, or it has problems beyond the scope of this script.')

    # check for 58/59 removal first
    if needs_58_59_removal(scc_attributes, video_attributes):
        new_filename = scc_filename.replace('.scc', '_58_59_removed.scc')
        new_lines = remove_58_59(scc_lines)
        logger.info('58/59-minute header removed and SCC timecode converted to 0-hour.')

    # then check for hour shift
    if needs_hour_shift(scc_attributes):
        new_filename = scc_filename.replace('.scc', '_hour_shifted.scc')
        new_lines = hour_shift(scc_lines, scc_attributes, video_attributes)
        logger.info('SCC timecode converted to 0-hour.')

    # check for frame rate
    if needs_frame_rate_convert(scc_attributes.framerate, video_attributes.framerate):
        # set up output filename suffix
        suffix = frame_rate_suffix(scc_attributes, video_attributes)
        # if new_file exists, an adjustment has already been made and we should use the new data
        try:
            frame_rate_convert_filename = new_filename.replace('.scc', suffix)
            frame_rate_convert_lines = colon_blow(new_lines, scc_attributes, video_attributes)
        except NameError:
            # new_file does not exist, so we go with the original data
            frame_rate_convert_filename = scc_filename.replace('.scc', suffix)
            frame_rate_convert_lines = colon_blow(scc_lines, scc_attributes, video_attributes)
        new_filename = frame_rate_convert_filename
        new_lines = frame_rate_convert_lines
        logger.info(f'SCC frame rate converted from {scc_attributes.framerate} ' \
                    f'to {video_attributes.framerate}.')

    # check for drop-frame
    if (needs_drop_frame_convert(scc_attributes.force_non_drop_frame,
                                 video_attributes.force_non_drop_frame)
        and not needs_frame_rate_convert(scc_attributes.framerate,
                                video_attributes.framerate)):
        # set up output filename suffix
        # we already know ndf_scc != ndf_video
        suffix = '_df_to_ndf.scc' if video_attributes.force_non_drop_frame else '_ndf_to_df.scc'
        # use previously-adjusted file if it exists
        try:
            df_ndf_convert_filename = new_filename.replace('.scc', suffix)
            df_ndf_convert_lines = drop_kick(new_lines, scc_attributes, video_attributes)
        except NameError:
            # new file doesn't exist
            df_ndf_convert_filename = scc_filename.replace('.scc', suffix)
            df_ndf_convert_lines = drop_kick(scc_lines, scc_attributes, video_attributes)
        new_filename = df_ndf_convert_filename
        new_lines = df_ndf_convert_lines
        if video_attributes.force_non_drop_frame:
            logger.info('SCC converted from Drop Frame to Non-Drop Frame.')
        else:
            logger.info('SCC converted from Non-Drop Frame to Drop Frame.')

    # la fin absolue du function
    logger.info(f'Adjusted filename: {new_filename}')
    return new_filename, new_lines

# MAIN
def lambda_handler(event, context):
    '''
    I think the message from SQS will look something like this:
    {
        'Records': [
            {
                'body': [
                    {
                        'key': 'vs_job_id',
                        'value': 'VX-1234'
                    },
                    {
                        'key': 's3_url',
                        'value': 's3://.../rthz-nqre_self_driver_2997DF.scc'
                    },
                    {
                        'key': 'output_s3_url',
                        'value': 's3://.../'
                    },
                    {
                        'key': 'mi_text_time_code_first_frame',
                        'value': '00:00:00;01'
                    },
                    {
                        'key': 'mi_time_code_first_frame',
                        'value': '00:00:00:00'
                    },
                    {
                        'key': 'mi_time_code_frame_rate',
                        'value': '29.97'
                    }
                ]
            }
        ]
    }
    '''
    # get the metadata from the event
    event_dict = build_event_dict(event)
    # we'll need this
    scc_filename = event_dict['s3_url'].split('/')[-1]

    try:
        # cast s3 object with bucket and key values as attributes
        s3_obj = s3_helper.S3Object(event_dict['s3_url'])

        # get scc data and split it into lines for handling
        scc_lines = s3_helper.read_text_from_s3(
            s3_obj.bucket,
            s3_obj.path,
            region_name=region_name)
        scc_lines = scc_lines.splitlines(keepends=True)
        logger.info('SCC contents successfully loaded.')

        # video/scc Timecode objects
        scc_attributes, video_attributes = set_up_attribute_objects(event_dict, scc_lines)

        # run scc data through correction
        new_filename, new_lines = scc_correction(
            scc_filename, scc_lines, scc_attributes, video_attributes)

        object_key = get_object_key(event_dict['output_s3_url'], s3_obj.bucket, new_filename)

        # build destination filepath and write new_lines
        s3_helper.write_text_to_s3(
            s3_obj.bucket,
            object_key,
            new_lines,
            region_name=region_name)

        # create and send job return doc
        result = {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json'
            },
            'body': json.dumps({
                'message': 'Adjusted SCC file successfully imported',
                'vs_job_id': event_dict['vs_job_id'],
            })
        }

        send_message_to_return_queue('scc_correction_return', result, event_dict['vs_job_id'])

        return {
            'statusCode': 200
        }

    # literally anything went wrong
    except Exception as e:
        logger.error(f'Error: {e}')

        error_result = {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json'
            },
            'body': json.dumps({
                'error': f'SCC correction failed. Error: {str(e)}',
                'vs_job_id': event_dict['vs_job_id']
            })
        }

        send_message_to_return_queue('scc_correction_return', error_result, event_dict['vs_job_id'])

        return {
            'statusCode': 500
        }
