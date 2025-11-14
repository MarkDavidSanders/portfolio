#!/usr/bin/python3
# script version and log level
script_version = "250202.19"
log_level = "INFO" # DEBUG INFO WARN ERROR
'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Environment
2. Item ID
3. Manzanita Output Filename
4. Manzanita Muxer Temp Profile
5. SCC Path to File (optional)

WHAT THIS SCRIPT DOES:
-Submits file to Manzanita with the given parameters
-Doesn't return anything; Vantage will check to see if output filename was created
'''
###CHANGE LOG###
'''
version 250202.19 - initial version
'''

#native imports
import subprocess
import sys
import os
import time
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

# args to variables
script_name =  cms_integration_logging.get_script_name(sys.argv[0])
arg_problem = False
if len(sys.argv) == 6:
    env = sys.argv[1].lower()
    item_id = sys.argv[2]
    output_path = sys.argv[3]
    template = sys.argv[4]
    scc_file_path = sys.argv[5]
elif len(sys.argv) == 5:
    env = sys.argv[1].lower()
    item_id = sys.argv[2]
    output_path = sys.argv[3]
    template = sys.argv[4]
    scc_file_path = False
elif len(sys.argv) > 6:
    arg_problem = 'Too many arguments!'
else:
    arg_problem = 'Not enough arguments!'

# logger setup - must have cms_integration_logging imported in project imports
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# start logging
logger.info(f'COMMENCING {script_name}.', extra=extras)

# bail out now if there was a problem with the number of args
# also bail out if script is not being run on a Windows machine
if arg_problem:
	logger.error(arg_problem)
	exit(1)
if sys.platform != 'win32':
    logger.error('Script must be run from Windows machine!')
    exit(1)

# log arg variables
logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'{item_id} provided as the item id.', extra=extras)
logger.info(f'{output_path} provided as the output file path.', extra=extras)
logger.info(f'{template} provided as the muxer template.', extra=extras)
if scc_file_path:
    logger.info(f'{scc_file_path} provided as the scc file path.', extra=extras)

#project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# custom functions	
def unix_to_windows(filepath):
    filepath = filepath.replace('file:///mnt/','').split('/')
    if filepath[0].lower() == 'xdrive':
        filepath[0] = '\\\\vc67.vcnyc.indemand.net\\vodstorage'
        return '\\'.join(filepath)
    elif filepath[0].lower() == 'mezz':
        filepath[0] = 'M:'
        return '\\'.join(filepath)

def shape_value(vs, token, target_storage, target_field, shapetag='original'):
    shape = eng_vs_token.get_shape_document(vs, token, item_id, shapetag)
    for file in shape.iter('file'):
        if file.find('storage').text == target_storage:
            if file.find(target_field) is not None:
                return file.find(target_field).text

def mux_submit(muxer,config_file):
    s = subprocess.Popen([muxer,config_file],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    results = s.communicate()
    if results[0] != '':
        return True, results[0]
    elif results[1] != '':
        return False, results[1]

def main(vs_token_data):
    local_storages = eng_vs_token.get_storage_groups(vs_token_data, 'local')
    current_storage = eng_vs_token.current_storage_id(vs_token_data, item_id, local_storages)
    original_file = unix_to_windows(shape_value(vs_token_data['vs'], vs_token_data['token'], current_storage, 'uri'))
    original_file = original_file.replace('%20',' ')

    logger.warning(f'Original File: {original_file}')
    logger.warning(f'Output Location: {output_path}')
    logger.warning(f'Template: {template}')

    muxer = 'C:\\Program Files\\Manzanita Systems\\MP2TSME 9\\mp2tsme.exe'
    template_file = f'M:\\mam\\admin\\integrations\\manzanita_profiles\\dev\\tsme\\{template}.cfg'
    config_store = f'M:\\mam\\admin\\integrations\\manzanita_profiles\\dev\\muxer_submission_templates\\{int(time.mktime(time.localtime()))}.cfg'

    if not os.access(template_file,os.R_OK):
        logger.error(f'Unable to access template. {template_file}')
        exit(1)

    # create folder
    output_folder = f'M:\\ADMIN\\Vantage Scratches\\Manzanita Scratch\\{item_id}'
    if not os.access(output_folder,os.R_OK):
        os.mkdir(output_folder)

    template_file = open(template_file)
    temp_config_file = open(config_store,'w')

    for line in template_file.readlines():
        if 'output_file' in line:
            temp_config_file.write(f'File = {output_path}\n')
        elif 'original_file' in line:
            temp_config_file.write(f'File = {original_file}\n')
        elif 'scc_file' in line:
            temp_config_file.write(f'File = {scc_file_path}\n')
        else:
            temp_config_file.write(line)

    temp_config_file.close()
    template_file.close()

    logger.warning('Starting Muxer Submit')
    complete, results = mux_submit(muxer,config_store)
    if complete:
        logger.warning('Completed Mux')
    else:
        logger.warning('Failed Mux')
    os.remove(config_store)
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
    vs_token_data = eng_vs_token.get_auto_refresh_token(vs,basic_auth,seconds)
    if not vs_token_data:
        logger.error("Didn't get token data from vidispine?")
        exit(2)
    try:
        main(vs_token_data)
        exit(0)
    except Exception as e:
        logger.error(traceback.format_exc())
        exit(1)