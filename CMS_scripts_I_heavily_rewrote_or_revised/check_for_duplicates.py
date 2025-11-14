#!/usr/bin/python3
# script version and log level
script_version = "250203.10"
log_level = "INFO" # DEBUG INFO WARN ERROR
'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. MD5 checksum value
2. Environment

WHAT THIS SCRIPT DOES:
-Gets Vault secrets
-Sends call to search VS for items with the md5 value
-Returns number of hits
'''

# native imports
import sys, traceback

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
try:
    md5 = sys.argv[1]
    env = sys.argv[2].lower()
except:
    arg_problem = f'Bad arguments provided. Expected md5 and environment values, got {sys.argv}'

# logger setup - must have cms_integration_logging imported
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# start logging
logger.info(f'COMMENCING {script_name}.', extra=extras)

# log arg variables
logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'{md5} provided as the md5.', extra=extras)

# project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# let's do it
search_doc = f'''
<ItemSearchDocument xmlns="http://xml.vidispine.com/schema/vidispine">
    <intervals>generic</intervals>
    <field>
        <name>original_shape_mi_original_shape_mi_md5_hash</name>
        <value>{md5}</value>
    </field>
</ItemSearchDocument>
'''

def main():
    secret_path = f'v1/secret/{env}/vidispine/vantage'
    vs_secret_data = eng_vault_agent.get_secret(secret_path)
    username = vs_secret_data["username"]
    password = vs_secret_data["password"]
    vs = vs_secret_data["api_url"]
    seconds = 60
    basic_auth = eng_vs_token.get_basic_auth(username,password)
    vs_token_data = eng_vs_token.get_token_no_auto_refresh(vs,basic_auth,seconds)
    if not vs_token_data:
        logger.error("Didn't get token data from vidispine?")
        exit(2)
    sys.stdout.write(str(len(eng_vs_token.search_items(vs_token_data, search_doc))))
    return True

if __name__ == "__main__":
    try:
        main()
        exit(0)
    except Exception as e:
        logger.error(traceback.format_exc())
        exit(1)
