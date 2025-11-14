#!/usr/bin/python3
# script version and log level
script_version = "250114.14"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Item ID
2. Environment

WHAT THE SCRIPT DOES:
-Imports a video_profiles dictionary and a valid_pairings dictionary (which identifies which profiles are valid for mezz or deriv subtypes)
-Gets a bunch of item metadata from Vidispine:
    -subtype
    -height/width
    -framerate
    -scan type
    -field dominance (False if scan type is progressive)
-Cross-checks everything but subtype in aggregate against video_profiles entries
    -Returns the number of matching profile or 0 if no match
-Exception handling:
    -If profile 23, makes sure that the codec is mxf
    -If profile 30, checks file_information_exception_framesize for "True" ¯\_(ツ)_/¯
-Creates "profile descrption" value out of video width, scan type, and framerate
-Stamps metadata:
    -mezz/deriv_qc_orig_video_profile_number (profile number)
    -mezz/deriv_qc_orig_video_profile_description (profile description)
    -mezz/deriv_qc_orig_category_results_video_profile (Pass/Fail value based on whether or not there was a profile match)
    -mezz/deriv_qc_orig_category_results_video_profile_description ("Profile is cool / not cool / unknown")
'''

###CHANGE LOG###
'''
version 250114.14 - initial version
'''

# native imports
import sys

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

# args to variables
arg_problem = False
if len(sys.argv) > 3:
    arg_problem = "Too many args provided!"
elif len(sys.argv) < 3:
    arg_problem = "Not enough args provided!"
else:
    script_name = cms_integration_logging.get_script_name(sys.argv[0])
    item_id = sys.argv[1]
    env = sys.argv[2]

# logger setup - must have cms_integration_logging imported
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# start logging
logger.info(f'COMMENCING {script_name}.', extra=extras)
# bail out now if there was a problem with the args.
if arg_problem:
	logger.error(arg_problem)
	exit(1)

# log arg variables
logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'{item_id} provided as the item.', extra=extras)

# project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# dictionary for reference
from video_profiles import video_profiles, valid_pairings

# function(s)
def determine_profile(height,width,framerate,scan_type,field_dominance,profiles):
    for key in profiles.keys():
        profile = profiles[key]
        if profile['height'] == height and profile['framerate'] == framerate and profile['scan_type'] == scan_type:
            if profile['field_dominance'] == field_dominance:
                if profile['width']:
                    if profile['width'] == width:
                        return key
                elif not profile['width'] and width != '528':
                    return key
    return 0

# indemand secretssssssssss
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

subtype = eng_vs_token.get_group_metadata_value(token_data,item_id,'file_information_subtype')
subtype = 'mezz' if 'mezz' in subtype.lower() else 'deriv'

framescan_results = eng_vs_token.get_group_metadata_value(token_data,item_id,f'{subtype}_qc_orig_category_results_framescan')

height = eng_vs_token.get_system_metadata_value(token_data,item_id,'originalHeight')
width = eng_vs_token.get_system_metadata_value(token_data,item_id,'originalWidth')
framerate = str(round(float(eng_vs_token.get_group_metadata_value(token_data,item_id,f'original_shape_mi_framerate')),2))

logger.warning(f'height: {height}, width: {width}, framerate: {framerate}')

if 'pass' in framescan_results.lower():
    scan_type = eng_vs_token.get_group_metadata_value(token_data,item_id,f'{subtype}_qc_orig_header_info_video_scan').lower()
    if 'interlaced' in scan_type:
        scan_split = scan_type.split(' ')
        scan_type = scan_split[0]
        field_dominance = ' '.join(scan_split[1:])
    else:
        field_dominance = False
else:
    scan_type = eng_vs_token.get_group_metadata_value(token_data,item_id,f'{subtype}_qc_orig_scan_analysis_type').lower()
    if 'interlaced' in scan_type:
        scan_type, field_dominance = scan_type.split(',')
        scan_type = scan_type.strip()
        field_dominance = field_dominance.strip()
    else:
        field_dominance = False

logger.warning(f'field dominance: {field_dominance}, scan type: {scan_type}')
profile = determine_profile(height,width,framerate,scan_type,field_dominance,video_profiles)

if profile == 23:
    codec = eng_vs_token.get_group_metadata_value(token_data,item_id,f'original_shape_mi_video_codec')
    if 'mxf' in codec.lower():
        profile = 23
    else:
        profile = 0

if profile == 30:
    exception = eng_vs_token.get_group_metadata_value(token_data,item_id,f'file_information_exception_framesize')
    if exception == 'True':
        profile = 30
    else:
        profile = 0

profile_number = int(profile)
profile_string = f'{video_profiles[profile_number]["height"]}{video_profiles[profile_number]["scan_type"][0]}/{video_profiles[profile_number]["framerate"]}' if profile_number != 0 else 'Unknown'

if profile_number == 0:
    profile_description = 'WARNING: Unknown'
    profile_result = 'Fail'
elif profile_number in valid_pairings[subtype]:
    profile_description = f'A video profile of {profile_string} is acceptable'
    profile_result = 'Pass'
else:
    profile_description = f'WARNING: {profile_string} is unacceptable'
    profile_result = 'Fail'

logger.warning(f'Profile Num {profile_number}')
logger.warning(f'Profile String {profile_string}')

updates = {
        1: {
            'group': f'{subtype}_qc_orig_video_profile',
            'field': f'{subtype}_qc_orig_video_profile_number',
            'value': str(profile_number)
        },
        2: {
            'group': f'{subtype}_qc_orig_video_profile',
            'field': f'{subtype}_qc_orig_video_profile_description',
            'value': profile_string
        },
        3: {
            'group': f'{subtype}_qc_orig_category_results',
            'field': f'{subtype}_qc_orig_category_results_video_profile',
            'value': profile_result
        },
        4: {
            'group': f'{subtype}_qc_orig_category_results',
            'field': f'{subtype}_qc_orig_category_results_video_profile_description',
            'value': profile_description
        }
}

for update in updates:
    vs_group = updates[update]['group']
    vs_field = updates[update]['field']
    vs_value = updates[update]['value']
    metadata = eng_vs_token.make_group_metadata_doc(vs_group,vs_field,vs_value)
    u = eng_vs_token.put_item_metadata(token_data,item_id,metadata)

    logger.warning(f'Metadata update: group {vs_group}, field {vs_field}, value {vs_value}')
    logger.warning(f'Update status code: {u}')

exit(0)