#!/usr/bin/python3
# script version and log level
script_version = "241212.16"
log_level = "INFO" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Item ID
2. Environment

WHAT THIS SCRIPT DOES:
-Hits up item's VS metadata for shape document and metadata fields:
    -file_information_subtype
    -originalAudioCodec
    -file_information_exception_audio_bitrate
-Checks subtype for mezz/deriv designation
-Builds dictionary of audio tracks from the audioComponent shape
-Extracts channel count and bitrate from each audio track
-Validates channel count/bitrate per track according to subtype
    -Special checks for Carnegie Hall 4K content
-Writes up a little message per bitrate value saying "valid" or "not valid"
-Stamps item's metadata with bitrate values and little messages
    -mezz/deriv_qc_orig_category_results_audio_bitrate
    -mezz/deriv_qc_orig_category_results_audio_bitrate_description
'''

###CHANGE LOG###
'''
version 241212.16 - initial version
'''

# native imports
import requests
from requests.exceptions import HTTPError
import sys
import traceback
import xml.etree.ElementTree as ET

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
if len(sys.argv) == 3:
	item_id = sys.argv[1]
	env = sys.argv[2].lower()
else:
	if len(sys.argv) > 3:
		arg_problem = "Too many args provided!"
	else:
		arg_problem = "Not enough args provided!"

# logger setup - must have cms_integration_logging imported in project imports
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# bail out now if there was a problem with the number of args.
if arg_problem:
	logger.error(arg_problem)
	exit(1)
else:
	# start logging
	# extras used in the json logger
	extras = {"cms_environment": env, "script_version": script_version}
	logger.info(f'COMMENCING {script_name}.', extra=extras)

# log arg variables
logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'{item_id} provided as the item.', extra=extras)

# project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# bespoke functions
def get_shape_doc(vs,token,item_id,shape_tag,storage_group,return_format):
	url = f'{vs}API/item/{item_id}?storageGroup={storage_group}&content=shape&tag={shape_tag}'
	headers = {
		'Accept': f'application/{return_format}',
		'Authorization': f'token {token}'
	}
	try:
		response = requests.request("GET", url, headers=headers)
		response.raise_for_status()  # Raises an HTTPError if the response was unsuccessful
		if return_format == 'xml':
			res = response.content
			res = res.decode(encoding='utf-8', errors='strict')
			# because I hate dealing with the namespace in ET
			res = res.replace(' xmlns=\"http://xml.vidispine.com/schema/vidispine\"', "")
			return res
		else:
			# json
			return response.text
	except HTTPError as http_err:
		logger.error(f'HTTP error occurred: {http_err}')
		exit(1)
	except Exception as err:
		logger.error(f'Other error occurred: {err}')
		exit(1)

def mezz_valid_bitrate(codec,bitrate,channel_count,bitrate_exception):
    if channel_count == 2 and bitrate >= 192000:
        return True
    elif channel_count == 6:
        if codec in ['ac3','aac','mpeg'] and (bitrate >= 640000 or(bitrate_exception and bitrate >= 384000)):
            return True
        elif codec == 'eac3' and bitrate >= 448000:
            return True
    elif channel_count == 8 and codec == 'eac3' and bitrate >= 960000:
        return True
    return False

def deriv_valid_bitrate(codec,bitrate,channel_count,first_track=False):
    if channel_count == 2:
        if bitrate == 192000:
            return True
        elif bitrate == 128000 and not first_track:
            return True
        elif codec == 'mp2' and bitrate == 384000:
            return True
        elif codec == 'aac' and bitrate >= 95800 and bitrate <= 96200:
            return True
    if channel_count == 6:
        if bitrate == 448000 or bitrate == 384000:
            return True
        elif codec == 'aac' and bitrate >= 254700 and bitrate <= 257300:
            return True

def make_group_metadata_doc(vs_group,vs_field,vs_value):
	metadata = {
		"timespan": [
			{
				"start": "-INF",
				"end": "+INF",
				"group": [
					{
						"name": vs_group,
						"field": [
							{
								"name": vs_field,
								"value": [
									{
										"value": vs_value
									}
								]
							}
						]
					}
				]
			}
		]
	}
	return metadata

def main():
    # get_vault_secret_data function returns a dict
    secret_path = f'v1/secret/{env}/vidispine/vantage'
    vs_secret_data = eng_vault_agent.get_secret(secret_path)
    username = vs_secret_data["username"]
    password = vs_secret_data["password"]
    vs = vs_secret_data["api_url"]
    seconds = 60
    basic_auth = eng_vs_token.get_basic_auth(username,password)
    token_data = eng_vs_token.get_token_no_auto_refresh(vs,basic_auth,seconds)
    if token_data:
        token = token_data["token"]
    else:
        logger.error("Didn't get token data from vidispine?")
        exit(2)
    
    # get shape doc and metadata
    shape_doc = get_shape_doc(vs,token,item_id,'original','local','xml')
    codec = eng_vs_token.get_system_metadata_value(token_data,item_id,'originalAudioCodec')
    bitrate_exception = eng_vs_token.get_group_metadata_value(token_data,item_id,'file_information_exception_audio_bitrate')
    bitrate_exception = True if bitrate_exception == 'True' else False
    subtype = eng_vs_token.get_group_metadata_value(token_data,item_id,'file_information_subtype')
    if subtype == None:
        logger.error('Subtype not found!')
        exit(1)
    if 'mezz' in subtype.lower():
        subtype = 'mezz'
    elif 'deriv' in subtype.lower():
        subtype = 'deriv'
    else:
        logger.error(f'Weird subtype! {subtype}')
        exit(1)

    # variable prep and track info compilation
    tracks = {}
    result = 'Pass'
    result_list = []

    # get_shape_doc returns a string, we want an XML tree
    shape_doc_tree = ET.fromstring(shape_doc)
    for track,component in enumerate(shape_doc_tree.findall('shape/audioComponent'),start=1):
        tracks[track] = component

    # validation
    for track in tracks.keys():
        first_track = True if track == 1 else False
        channel_count = int(tracks[track].find('channelCount').text)
        bitrate = int(tracks[track].find('bitrate').text)
        if subtype == 'mezz':
            valid = mezz_valid_bitrate(codec,bitrate,channel_count,bitrate_exception)
        else:
            valid = deriv_valid_bitrate(codec,bitrate,channel_count,first_track)
        if valid:
            # conform CH 4k bitrates so they don't look weird to the user
            if bitrate >= 95800 and bitrate <= 96200:
                bitrate = 96000
            elif bitrate >= 254700 and bitrate <= 257300:
                bitrate = 256000
            result_list.append(f'Track {track}: A bitrate of {bitrate} is acceptable.')
        else:
            result_list.append(f'WARNING: A bitrate of {bitrate} on Track {track} is unacceptable.')
            result = 'Fail'
        logger.warning(f'Validation result: {result}. {result_list[-1]}')

    # it puts the results in the metadata or else it gets the hose again
    vs_group = f'{subtype}_qc_orig_category_results'
    vs_field = f'{subtype}_qc_orig_category_results_audio_bitrate'
    logger.warning(f'Metadata update: group {vs_group}, field {vs_field}, value {result}')
    metadata = make_group_metadata_doc(vs_group,vs_field,result)
    u = eng_vs_token.put_item_metadata(token_data,item_id,metadata)
    logger.warning(f'Update status code: {u}')

    vs_field += '_description'
    vs_value = ' '.join(result_list)
    logger.warning(f'Metadata update: group {vs_group}, field {vs_field}, value {vs_value}')
    metadata = make_group_metadata_doc(vs_group,vs_field,vs_value)
    u = eng_vs_token.put_item_metadata(token_data,item_id,metadata)
    logger.warning(f'Update status code: {u}')

try:
	main()
	exit(0)
except Exception as e:
	logger.error(traceback.format_exc())
	exit(1)