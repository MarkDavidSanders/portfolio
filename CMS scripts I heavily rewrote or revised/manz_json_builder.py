#!/usr/bin/python3
# script version and log level
script_version = "250130.13"
log_level = "INFO" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Item ID
2. Environment

WHAT THIS SCRIPT DOES:
-Pulls in a template of all metadata fields used in the Manzanita QC Report
-GETs manz test result and originalFilename values from item's metadata
-Creates JSON object of manz test results, populating each sub-section with the item's metadata field values
-Returns JSON object to Vidispine as item's deriv_qc_orig_manzanita_legacy_results_json field value
'''
###CHANGE LOG###
'''
version 250130.13 - initial version
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

# project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# custom functions
def build_manz_json(vs_token_data, item_id, env):
  if env == 'prod':
    target_system = 'production'
  else:
     target_system = env

  if sys.platform == 'win32':
    template = 'M:\\mam\\admin\\integrations\\autoqc\\manz_legacy_config.xml'
  elif sys.platform == 'darwin':
    template = '/Volumes/Mezz/mam/admin/integrations/autoqc/manz_legacy_config.xml'
  else:
    template = '/mnt/Mezz/mam/admin/integrations/autoqc/manz_legacy_config.xml'

  template = ET.parse(template)

  report = {}
  report['manz_legacy_qc'] = {}
  report['manz_legacy_qc']['title'] = 'Manzanita Legacy Test Report'
  report['manz_legacy_qc']['file_name'] = eng_vs_token.get_system_metadata_value(vs_token_data,item_id,'originalFilename')
  report['manz_legacy_qc']['manzanita_legacy_result'] = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,'deriv_qc_orig_category_results_manzanita_legacy_verification')
  report['manz_legacy_qc']['section'] = []

  for x in template.findall('system'):
    if x.attrib['type'] == target_system:
      system = x

  for x in system.findall('report/section'):
    s = {'sub_section':[],'_name':x.attrib['name']}
    for y in x.findall('sub_section'):
      t = {'test':[],'_name':y.attrib['name']}
      for z in y.findall('test'):
        result = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,z.find('result').text)
        if result:
          description = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,z.find('description').text)
          r = {'_name':z.attrib['name'],'result':result.upper(),'description':description}
          t['test'].append(r)
      s['sub_section'].append(t)
    report['manz_legacy_qc']['section'].append(s)

  logger.warning('Filled JSON')

  metadata_update_doc = eng_vs_token.make_group_metadata_doc('deriv_qc_orig_manzanita_legacy_results','deriv_qc_orig_manzanita_legacy_results_json',json.dumps(report))
  
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
      build_manz_json(token_data, item_id, env)
      exit(0)
    except Exception as e:
      logger.error(traceback.format_exc())
      exit(1)
  else:
    logger.error("Didn't get token data from vidispine?")
    exit(2)