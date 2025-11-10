#!/usr/bin/python3
# script version and log level
script_version = "250127.13"
log_level = "INFO" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Item ID
2. Environment

WHAT THIS SCRIPT DOES:
-Pulls in a template of all metadata fields used in the Mezzanine AutoQC Report
-GETs aggregate_test_result and originalFilename values from item's metadata
-Creates JSON object of aggregate test results, populating each sub-section with the item's metadata field values
-Returns JSON object to Vidispine as item's aggregate_test_results_json field value
'''
###CHANGE LOG###
'''
version 250127.13 - initial version
'''

#native imports
import json
import xml.etree.ElementTree as ET
import sys
import traceback

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

#project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# custom functions
def build_json(vs_token_data, item_id, env="PROD"):
  report = {'qc_report':{'title':'','aggregate_result':'','file_name':'','section':[]}}

  logger.warning('Started Aggregate Json Builder')

  if sys.platform == 'win32':
    template = ET.parse('M:\\mam\\admin\\integrations\\autoqc\\autoQC_test_results_config.xml')
  elif sys.platform == 'darwin':
    template = ET.parse('/Volumes/Mezz/mam/admin/integrations/autoqc/autoQC_test_results_config.xml')
  else:
    template = ET.parse('/mnt/Mezz/mam/admin/integrations/autoqc/autoQC_test_results_config.xml')

  logger.warning('Successfully parsed xml')

  if env == 'prod':
    target_system = 'production'
  else:
    target_system = env

  subtype = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,'file_information_subtype')

  if 'mezz' in subtype.lower():
    subtype = 'mezz'
    title = 'Mezzanine Auto QC Report'
  elif 'deriv' in subtype.lower():
    subtype = 'deriv'
    title = 'Derivative Auto QC Report'
  else:
    logger.error(f'Invalid Subtype {subtype}')
    exit(0)

  logger.warning(f'Subtype: {subtype}')

  aggregate_result = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,'aggregate_test_result')
  file_name = eng_vs_token.get_system_metadata_value(vs_token_data,item_id,'originalFilename')

  report['qc_report']['title'] = title
  report['qc_report']['aggregate_result'] = aggregate_result.upper()
  report['qc_report']['file_name'] = file_name
  report['qc_report']['section'] = []

  for x in template.findall('system'):
    if x.attrib['type'] == target_system:
      system = x

  for x in system.findall('report'):
    if x.attrib['type'] == subtype:
      subtype_report = x

  for x in subtype_report.findall('section'):
    s = {'sub_section':[],'_name':x.attrib['name']}
    for y in x.findall('sub_section'):
      t = {'test':[],'_name':y.attrib['name']}
      for z in y.findall('test'):
        result = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,z.find('result_source').text)
        if result:
          description = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,z.find('description_source').text)
          r = {'_name':z.attrib['name'],'result':result.upper(),'description':description}
          t['test'].append(r)
      s['sub_section'].append(t)
    report['qc_report']['section'].append(s)

  logger.warning('Filled JSON')

  metadata_update_doc = eng_vs_token.make_group_metadata_doc('aggregate_test','aggregate_test_results_json',json.dumps(report))
  
  r = eng_vs_token.put_item_metadata(vs_token_data,item_id,metadata_update_doc)
  logger.warning(f'Update response: {r}')
  exit(0)

if __name__ == "__main__":
  secret_path = f'v1/secret/{env}/vidispine/vantage'
  vs_secret_data = eng_vault_agent.get_secret(secret_path)
  username = vs_secret_data["username"]
  password = vs_secret_data["password"]
  vs = vs_secret_data["api_url"]
  vs_auth = eng_vs_token.get_basic_auth(username,password)
  auto_refresh = 'false'
  ttl = 10
  token_data = eng_vs_token.get_token_no_auto_refresh(vs, vs_auth, ttl)
  if token_data:
    try:
      build_json(token_data, item_id, env)
      exit(0)
    except Exception as e:
      logger.error(traceback.format_exc())
      exit(1)
  else:
    logger.error("Didn't get token data from vidispine?")
    exit(2)
