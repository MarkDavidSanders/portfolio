#!/usr/bin/python3
# script version and log level
script_version = "241208.17"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Item ID
2. "file_information_uwf_profile_description" metadata value
3. Environment

WHAT THE SCRIPT DOES:
-Imports dictionaries from uwf_profiles.py
-GETs file_information_vendor_folder from Vidispine and stores it in a variable
    -assigns value of 'Unknown' if VS field is empty/missing
-Splits the file_information_uwf_profile_description argument into its component values, stores the values in variables, and stores the variables in a dictionary
-Uses the audio codec and channel configuration from file_information_uwf_profile_description to calculate the number of audio tracks in the item
-GETs originalWidth value from Vidispine, stores it in variable
-Builds a dict_key object of UWF profiles from the profiles dictionary
-Uses the item's video width and audio codec/track data to filter out ineligible profiles from the dict_key object
-Cross-checks the values in the uwf_profile_description dict against the remaining entries in the dict_key object and builds a new array of profile matches
-Cross-checks audio track data against the new array to return an even smaller array
-Repeats the above process using video bitrate
-If the refined eligible_profiles array has two profiles left, the profile with the smaller bitrate is removed
-If the refined array only has one profile left, the original profile dictionary is double-checked to make sure all values match
    -If profile is a confirmed match, the profile's key is stored in a uwf_profile variable
    -uwf_profile = 0 if no match
-If neither 1 nor 2 profiles remain, we build a new dict_key object from the exceptions dict and start over
-The vendor_folders dict is indexed using the uwf_profile number as key
    -If the resulting value matches the vendor_folder value, vendor_match = True
-A new studio_string variable is created by cross-checking the vendor_folder value against the provider_strings dictionary
-If uwf_profile = 0, profile_bool = False; otherwise, True
-At long last, the following file_information field/value pairings are created and sent to Vidispine via PUT call:
    -file_information_uwf_profile_number: uwf_profile
    -file_information_uwf_vendor_match: vendor_match
    -file_information_uwf_possible_studio: studio_string
    -file_information_uwf_profile_description: profile_string
    -file_information_uwf_profile: profile_bool
'''

#native imports
import sys
import traceback
import re

# custom support packages live in the scripts/packages/ directory
# add path to packages for import
script_path = sys.argv[0]
if 'linux' in sys.platform or 'darwin' in sys.platform:
    packages_path = script_path[:script_path.rfind('/scripts/')]+'/packages/'
else:
    packages_path = script_path[:script_path.rfind('\\scripts\\')]+'\\packages\\'
sys.path.insert(0,packages_path)

# add variable for path to crt_file (DigiCertCA.crt) which is in the packages path above
crt_file = packages_path + 'DigiCertCA.crt'

# import logging module
import cms_integration_logging # need this for everything

# args to variables:
script_name =  cms_integration_logging.get_script_name(sys.argv[0])
arg_problem = False
if len(sys.argv) == 4:
	item_id = sys.argv[1]
	profile_string = sys.argv[2]
	env = sys.argv[3].lower()
else:
	if len(sys.argv) > 4:
		arg_problem = "Too many args provided!"
	else:
		arg_problem = "Not enough args provided!"

# logger setup - must have cms_integration_logging imported in project imports
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# start logging
logger.info(f'COMMENCING {script_name}.', extra=extras)
# bail out now if there was a problem with the number of args.
if arg_problem:
	logger.error(arg_problem)
	exit(1)

# log arg variables
logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'{item_id} provided as the item.', extra=extras)
logger.info(f'{profile_string} provided as the uwf profile description.', extra=extras)

# project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# the big dict
import uwf_profiles as uwf

# custom functions
def convert_frame_rate(frame_rate):
    valid_frame_rates = {23.98:23.98,29.98:29.97,29.97:29.97,59.94:59.94}
    splits = list(frame_rate)
    splits.insert(2,'.')
    frame_rate = ''.join(splits)
    try:
        return valid_frame_rates[round(float(frame_rate),2)]
    except:
        return float(frame_rate)

def profile_match(profiles, profiles_to_check, field, value):
    eligible_profiles = []
    for profile in profiles_to_check:
        if profiles[profile][field] == value:
            eligible_profiles.append(profile)
            logger.debug(f'STRING Possible Match Profile: {profile}. Field {field}')
        elif (type(profiles[profile][field]) == int or type(profiles[profile][field]) == float) and value >= profiles[profile][field] and field != 'frame_rate':
            logger.debug(f'INT Possible Match Profile: {profile}. Field {field}')
            eligible_profiles.append(profile)
        elif type(profiles[profile][field]) == float and value == profiles[profile][field]:
            logger.debug(f'FLOAT Possible Match Profile: {profile}. Field {field}')
            eligible_profiles.append(profile)
        else:
            logger.debug(f'NO MATCH {profile} Field {field}')
    return eligible_profiles

def profile_match_audio_field(profiles, profiles_to_check, field, bitrate, layout):
    eligible_profiles = []
    for profile in profiles_to_check:
        if profiles[profile][field]:
            if bitrate >= profiles[profile][field]['bitrate'] and layout == profiles[profile][field]['layout']:
                logger.debug(f'Possible Match Profile: {profile}. Field {field}')
                eligible_profiles.append(profile)
    return eligible_profiles

def exception_max_bitrate(profiles, profiles_to_check, video_bitrate):
    eligible_profiles = []
    for profile in profiles_to_check:
        if video_bitrate < profiles[profile]['max_video_bitrate']:
            eligible_profiles.append(profile)
            logger.debug(f'Possible Match Profile {profile} Field Max Video Bitrate')
    return eligible_profiles

def confirm_profile(target_profile, collected_data):
    for key in collected_data.keys():
        if collected_data[key] != target_profile[key]:
            return False
    return True

def split_profile(profile_string):
    profile_string_split = profile_string.split("_")

    video_codec = profile_string_split[0]
    video_quality = profile_string_split[1]
    video_bitrate = profile_string_split[2]
    video_bitrate_number = int(re.match('\d+',video_bitrate).group())
    frame_size_and_scan_type = profile_string_split[3]
    frame_size = re.match('\d+',frame_size_and_scan_type).group()

    if 'i' in frame_size_and_scan_type:
        scan_type = 'interlaced'
    else:
        scan_type = 'progressive'

    frame_rate = convert_frame_rate(profile_string_split[4])
    primary_audio_codec = profile_string_split[5]
    audio_info = profile_string_split[6:]

    return (video_codec, video_quality, video_bitrate_number, 
            frame_size, scan_type, frame_rate, primary_audio_codec,
            audio_info)

def determine_audio_info(primary_audio_codec, audio_info):
    if primary_audio_codec == 'PCM':
        number_of_tracks = len(audio_info)
    else:
        number_of_tracks = len(audio_info) / 2

    audio_tracks = {}
    count = 0

    for track in range(0,len(audio_info)):
        if track % number_of_tracks == 0 or primary_audio_codec == 'PCM':
            track_info = {}
            track_info['layout'] = audio_info[track]
            if primary_audio_codec != 'PCM':
                track_info['bitrate'] = int(re.match('\d+',audio_info[track + 1]).group())
            else:
                track_info['bitrate'] = False
            audio_tracks[count] = track_info
            count += 1
            if number_of_tracks == 1:
                break
    return audio_tracks

def determine_profile(token_data,item_id,profile_string):
    (video_codec, video_quality, video_bitrate_number, 
    frame_size, scan_type, frame_rate, primary_audio_codec,
    audio_info) = split_profile(profile_string)

    collected_data = {'video_codec': video_codec, 
                      'definition': video_quality,
                      'frame_rate': frame_rate,
                      'scan_type': scan_type,
                      'frame_height': frame_size,
                      'audio_codec': primary_audio_codec}
    
    audio_tracks = determine_audio_info(primary_audio_codec, audio_info)

    logger.debug(f'Collected metadata: {collected_data}')
    logger.debug(f'Video bitrate: {video_bitrate_number}.')
    logger.debug(f'Audio info: {audio_info}.')
    logger.debug(f'Audio tracks: {audio_tracks}')
    
    # build set of eligible profiles and make a copy for iteration
    eligible_profiles = set(uwf.profiles)
    eligible_profiles_reference = eligible_profiles.copy()

    # get dat width
    width = eng_vs_token.get_system_metadata_value(token_data,item_id,'originalWidth')
    if not width:
        logger.error('originalWidth value not found in metadata! WTF.')
        exit(1)

    logger.debug(f'originalWidth: {width}')

    # remove eligible profiles that don't match the audio profile
    if len(audio_tracks) > 1 and audio_tracks[0]['layout'] != '20':
        additional_tracks = {'layout':audio_tracks[1]['layout'],'bitrate':audio_tracks[1]['bitrate']}
        for profile in eligible_profiles_reference:
            if uwf.profiles[profile]['additional_audio_tracks'] == False:
                eligible_profiles.remove(profile)
    else:
        additional_tracks = False
        for profile in eligible_profiles_reference:
            if uwf.profiles[profile]['additional_audio_tracks'] != False:
                eligible_profiles.remove(profile)

    primary_fields_to_check = {'video_codec':video_codec,'definition':video_quality,'video_bitrate':video_bitrate_number,
                               'audio_codec':primary_audio_codec,'frame_rate':frame_rate,'scan_type':scan_type,'frame_width':width}

    # filter eligible profiles by individual primary field values
    for field in primary_fields_to_check:
        eligible_profiles = profile_match(uwf.profiles,eligible_profiles,field,primary_fields_to_check[field])

    # filter by audio info
    eligible_profiles = profile_match_audio_field(uwf.profiles,eligible_profiles,'audio_config',audio_tracks[0]['bitrate'],audio_tracks[0]['layout'])

    if additional_tracks:
        eligible_profiles = profile_match_audio_field(uwf.profiles,eligible_profiles,'additional_audio_tracks',audio_tracks[1]['bitrate'],audio_tracks[1]['layout'])

    logger.warning(f'Eligible Profiles: {eligible_profiles}')

    # if two profiles remain, keep the one with the larger bitrate
    if len(eligible_profiles) == 2:
        if uwf.profiles[eligible_profiles[0]]['video_bitrate'] > uwf.profiles[eligible_profiles[1]]['video_bitrate']:
            eligible_profiles.remove(eligible_profiles[1])
        else:
            eligible_profiles.remove(eligible_profiles[0])

    # are we done yet?
    if len(eligible_profiles) == 1:
        if confirm_profile(uwf.profiles[eligible_profiles[0]],collected_data):
            return eligible_profiles[0]
        else:
            return 0

    # we couldn't find a match so we start over with exceptions dict
    eligible_profiles = set(uwf.exceptions)
    eligible_profiles_reference = eligible_profiles.copy()

    if len(audio_tracks) > 1 and audio_tracks[0]['layout'] != '20':
        additional_tracks = {'layout':audio_tracks[1]['layout'],'bitrate':audio_tracks[1]['bitrate']}
        for profile in eligible_profiles_reference:
            if uwf.exceptions[profile]['additional_audio_tracks'] == False:
                eligible_profiles.remove(profile)
    else:
        additional_tracks = False
        for profile in eligible_profiles_reference:
            if uwf.exceptions[profile]['additional_audio_tracks'] != False:
                eligible_profiles.remove(profile)

    # same primary fields as before
    for field in primary_fields_to_check:
        eligible_profiles = profile_match(uwf.exceptions,eligible_profiles,field,primary_fields_to_check[field])

    eligible_profiles = profile_match_audio_field(uwf.exceptions,eligible_profiles,'audio_config',audio_tracks[0]['bitrate'],audio_tracks[0]['layout'])

    if additional_tracks:
        eligible_profiles = profile_match_audio_field(uwf.exceptions,eligible_profiles,'additional_audio_tracks',audio_tracks[1]['bitrate'],audio_tracks[1]['layout'])

    eligible_profiles = exception_max_bitrate(uwf.exceptions, eligible_profiles, video_bitrate_number)

    logger.warning(f'Eligible Exceptions: {eligible_profiles}')

    # are we done yet?
    if len(eligible_profiles) == 1:
        if confirm_profile(uwf.exceptions[eligible_profiles[0]], collected_data):
            return eligible_profiles[0]
        else:
            return 0

    # one last try
    for profile in eligible_profiles:
        eligible_profiles = exception_max_bitrate(uwf.exceptions,eligible_profiles,video_bitrate_number)

    if len(eligible_profiles) == 1:
        if confirm_profile(uwf.exceptions[eligible_profiles[0]], collected_data):
            return eligible_profiles[0]
        else:
            return 0

    # profile match not found
    return 0

def main():
    # get_vault_secret_data function returns a dict
    secret_path = f'v1/secret/{env}/vidispine/vantage'
    vs_secret_data = eng_vault_agent.get_secret(secret_path)
    username = vs_secret_data["username"]
    password = vs_secret_data["password"]
    vs = vs_secret_data["api_url"]
    seconds = 60
    basic_auth = eng_vs_token.get_basic_auth(username,password)
    token_data = eng_vs_token.get_auto_refresh_token(vs,basic_auth,seconds)
    if not token_data:
        logger.error("Didn't get token data from vidispine?")
        exit(2)

    # assign metadata_update variables and build the update
    vendor_folder = eng_vs_token.get_group_metadata_value(token_data,item_id,'file_information_vendor_folder')
    if not vendor_folder:
        vendor_folder = 'Unknown'

    logger.warning(f'Vendor Folder is {vendor_folder}.')

    uwf_profile = determine_profile(token_data,item_id,profile_string)

    logger.warning(f'UWF Profile Number is {uwf_profile}.')

    if vendor_folder in uwf.vendor_folders[uwf_profile]:
        vendor_match = True
    else:
        vendor_match = False

    if vendor_match: 
        studio_string = uwf.provider_strings[vendor_folder]
    else:
        studio_string = uwf.provider_strings['Unknown']

    logger.warning(f'Studio is {studio_string}.')

    if uwf_profile != 0:
        profile_bool = True
    else:
        profile_bool = False
    
    metadata_updates = {
        1: {
            'group': 'file_information',
            'field': 'file_information_uwf_profile_number',
            'value': str(uwf_profile)
        },
        2: {
            'group': 'file_information',
            'field': 'file_information_uwf_vendor_match',
            'value': str(vendor_match)
        },
        3: {
            'group': 'file_information',
            'field': 'file_information_uwf_possible_studio',
            'value': studio_string
        },
        4: {
            'group': 'file_information',
            'field': 'file_information_uwf_profile_description',
            'value': profile_string
        },
        5: {
            'group': 'file_information',
            'field': 'file_information_uwf_profile',
            'value': str(profile_bool)
        },
    }

    # put the metadata in its place
    for update in metadata_updates:
        vs_group = metadata_updates[update]['group']
        vs_field = metadata_updates[update]['field']
        vs_value = metadata_updates[update]['value']
        metadata = eng_vs_token.make_group_metadata_doc(vs_group,vs_field,vs_value)
        u = eng_vs_token.put_item_metadata(token_data,item_id,metadata)

        logger.warning(f'Metadata update: group {vs_group}, field {vs_field}, value {vs_value}')
        logger.warning(f'Update status code: {u}')

    if int(uwf_profile) in uwf.exceptions.keys():
        vs_group, vs_field, vs_value = 'file_information', 'file_information_onboard_exception', 'True'
        metadata = eng_vs_token.make_group_metadata_doc(vs_group,vs_field,vs_value)
        u = eng_vs_token.put_item_metadata(token_data,item_id,metadata)

        logger.warning(f'Metadata update: group {vs_group}, field {vs_field}, value {vs_value}')
        logger.warning(f'Update status code: {u}')

        profile = uwf.exceptions[int(uwf_profile)]
        for field in profile['exception_fields']:
            vs_field = f'file_information_exception_{field}'    # group and value stay the same
            metadata = eng_vs_token.make_group_metadata_doc(vs_group,vs_field,vs_value)
            u = eng_vs_token.put_item_metadata(token_data,item_id,metadata)

            logger.warning(f'Metadata update: group {vs_group}, field {vs_field}, value {vs_value}')
            logger.warning(f'Update status code: {u}')

try:
	main()
	exit(0)
except Exception as e:
	logger.error(traceback.format_exc())
	exit(1)