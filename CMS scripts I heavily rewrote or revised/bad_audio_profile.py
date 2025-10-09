#!/usr/bin/python3
# script version and log level
script_version = "241217.14"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED:
1. Item ID
2. Audio profile number
3. Environment

WHAT THE SCRIPT DOES:
-Creates a timestamp for the current time
-Checks VS for file_information_subtype value
-Builds a dictionary of metadata fields and their respective values
    - {subtype}_wf_orig group:
        - _status, _audio_profile_status, _current_process, _audio_profile_end
    - {subtype}_qc_orig_audio_profile group:
        - _number, _description
    - {subtype}_qc_orig_category_results group:
        - _audio_profile, _audio_profile_description
    - aggregate_test group:
        - _status, _end, _date, _result
-Cycles through the dictionary to create metadata update groups and stamps them into the item's metadata one by one
-Runs workflow_run_time.py and aggregate_json_builder.py (see respective docstrings for details)
'''
###CHANGE LOG###
'''
version 241217.14 - initial version
'''

# native imports
import sys
import xml.etree.ElementTree as ET
from datetime import datetime

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
	audio_profile_number = sys.argv[2]
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
logger.info(f'{audio_profile_number} provided as the audio profile number.', extra=extras)

# project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# custom functions
def handle_bad_audio(vs_token_data, item_id, audio_profile_number, env):
    descriptions = {
        '998':'Stems',
        '999':'Unsupported audio format'
    }
    if audio_profile_number not in descriptions:
        logger.error(f'The provided audio profile number {audio_profile_number} is not actually bad!')
        exit(1)
    time = f'{datetime.isoformat(datetime.now())}-04:00'
    subtype = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,'file_information_subtype')
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
    
    updates = {
        f'{subtype}_wf_orig':[('status','Completed'),('audio_profile_status','Completed'),('current_process','None'),('audio_profile_end',time)],
        f'{subtype}_qc_orig_audio_profile':[('number',audio_profile_number),('description',descriptions[audio_profile_number])],
        f'{subtype}_qc_orig_category_results':[('audio_profile','Fail'),('audio_profile_description',f'WARNING: {descriptions[audio_profile_number]}')],
        'aggregate_test':[('status','Completed'),('end',time),('date',time),('result','Fail')]
    }

    for group in updates:
        for dataset in updates[group]:
            vs_group = group
            vs_field = f'{group}_{dataset[0]}'
            vs_value = dataset[1]
            logger.warning(f'Metadata update: group {vs_group}, field {vs_field}, value {vs_value}')
            metadata = {"timespan": [{"start": "-INF","end": "+INF",
                                     "group": [{"name": vs_group,
                                                "field": [{"name": vs_field,
                                                           "value": [{"value": vs_value}]}]}]}]}
            u = eng_vs_token.put_item_metadata(vs_token_data,item_id,metadata)
            logger.warning(f'Update status code: {u}')
            
    eng_vs_token.determine_run_time(vs_token_data, item_id, 'qc', env)
    eng_vs_token.build_json(item_id, env)
    return True

if __name__ == '__main__':
    # get_vault_secret_data function returns a dict
    secret_path = f'v1/secret/{env}/vidispine/vantage'
    vs_secret_data = eng_vault_agent.get_secret(secret_path)
    username = vs_secret_data["username"]
    password = vs_secret_data["password"]
    vs = vs_secret_data["api_url"]
    seconds = 60
    basic_auth = eng_vs_token.get_basic_auth(username,password)
    token_data = eng_vs_token.get_token_no_auto_refresh(vs,basic_auth,seconds)
    if not token_data:
        logger.error("Didn't get token data from vidispine?")
        exit(2)
    handle_bad_audio(token_data, item_id, audio_profile_number, env)
    exit(0)