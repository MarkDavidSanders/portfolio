#!/usr/bin/python3
# script version and log level
script_version = "241217.14"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED:
1. Item ID
2. Vantage workflow ('qc' or 'fileinfo')
3. Environment

WHAT THE SCRIPT DOES:
-Checks Vidispine for values of the the 'start' and 'end' fields in the metadata group indicated by the workflow argument
-Subtracts start time from end time to get runtime
-Stamps 'runtime' field of the metadata group
-Checks VS again for file type
  -If type is 'video' and workflow argument is 'qc', gets 'durationSeconds' value from metadata
  -Divides durationSeconds value by runtime and stamps 'aggregate_test_realtime' with the result
'''

###CHANGE LOG###
'''
version 241217.14 - initial version
'''

# native imports
import sys
import datetime
import iso8601

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
	workflow = sys.argv[2]
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
logger.info(f'{workflow} provided as the workflow.', extra=extras)

# project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# custom functions
def determine_run_time(token_data, item_id, workflow, env):
  logger.warning(f'Starting Run Time Update for {item_id} {workflow} in {env} environment')
  workflows = {
            'qc':
              {'start':'aggregate_test_start','end':'aggregate_test_end','group':'aggregate_test','field':'aggregate_test_runtime'},
            'fileinfo':
              {'start':'file_information_start','end':'file_information_end','group':'file_information','field':'file_information_runtime'}
              }

  # check for field presence
  start_time = eng_vs_token.get_group_metadata_value(token_data,item_id,workflows[workflow]['start'])
  end_time = eng_vs_token.get_group_metadata_value(token_data,item_id,workflows[workflow]['end'])
  
  if start_time == None or end_time == None:
    logger.warning('Missing start or end time')
    exit(0)

  start_time = iso8601.parse_date(start_time)
  logger.warning(f'Start time is {start_time}')

  end_time = iso8601.parse_date(end_time)
  logger.warning(f'End time is {end_time}')

  run_time = end_time - start_time
  logger.warning(f'Running time is {run_time.seconds} seconds')

  metadata_document = {"timespan": [{"start": "-INF","end": "+INF",
                                     "group": [{"name": workflows[workflow]['group'],
                                                "field": [{"name": workflows[workflow]['field'],
                                                           "value": [{"value": str(run_time.seconds)}]}]}]}]}

  u = eng_vs_token.put_item_metadata(token_data,item_id,metadata_document)
  logger.warning(f'Updated Runtime as {str(run_time.seconds)}. Status code: {u}')

  asset_type = eng_vs_token.get_group_metadata_value(token_data,item_id,'file_information_asset_type')

  if asset_type.lower() == 'video' and workflow == 'qc':
    duration = float(eng_vs_token.get_system_metadata_value(token_data,item_id,'durationSeconds'))
    percent = round(run_time.seconds / duration,2)
    metadata = {"timespan": [{"start": "-INF","end": "+INF",
                              "group": [{"name": 'aggregate_test',
                                         "field": [{"name": 'aggregate_test_realtime',
                                                    "value": [{"value": str(percent)}]}]}]}]}
    u = eng_vs_token.put_item_metadata(token_data,item_id,metadata)
    logger.warning(f'Updated Realtime as {percent}. Status code: {u}')

  logger.warning('THE END.')
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
  determine_run_time(token_data, item_id, workflow, env)
  exit(0)