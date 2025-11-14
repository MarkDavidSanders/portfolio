#!/usr/bin/python3
# script version and log level
script_version = "250122.18"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Environment
2. Item ID
3 etc. Shape tag(s)
'''

import json, os, requests, sys

try:
    from urllib import quote_plus
except ImportError:
    from urllib.parse import quote_plus

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
if len(sys.argv) < 4:
    arg_problem = f"Bad arguments. Usage: {sys.argv[0]} environment item-id shape-tag(s)..."
else:
    env = sys.argv[1].upper()
    item_id = sys.argv[2]
    shape_tags = sys.argv[3:]

# logger setup - must have cms_integration_logging imported in project imports
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# start logging
logger.info(f'COMMENCING {script_name}.', extra=extras)

# bail out now if there was a problem with the number of args
if arg_problem:
	logger.error(arg_problem)
	exit(1)

# log arg variables
logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'{item_id} provided as the item id.', extra=extras)
logger.info(f'shape tags provided: {shape_tags}', extra=extras)

# env dict
ENVS = {
    "DEV": {
        "AP_API_URL": "http://10.12.4.15:85/api",
        "ANALYZE_URL": "http://10.12.4.15:85/api",
        "REPLACE_URL": "http://ap-nginx",
    },
    "UAT": {
        "AP_API_URL": "http://10.12.4.29:85/api",
        "ANALYZE_URL": "http://10.12.4.29:85/api",
        "REPLACE_URL": "http://vsautdev01.vcnyc.indemand.net:8080",
    },
    "PROD": {
        "AP_API_URL": "http://10.12.4.44:85/api",
        "ANALYZE_URL": "http://10.12.4.44:85/api",
        "REPLACE_URL": "http://vidispine01.vcnyc.indemand.net:8080",
    },
}

# here we go
if "__main__" == __name__:

    AP_API_URL = os.environ.get("AP_API_URL", ENVS.get(env, {}).get("AP_API_URL"))
    ANALYZE_URL = os.environ.get("ANALYZE_URL", ENVS.get(env, {}).get("ANALYZE_URL", AP_API_URL))
    REPLACE_URL = os.environ.get("REPLACE_URL", ENVS.get(env, {}).get("REPLACE_URL"))

    u = f'{AP_API_URL}/asset/{item_id}?content=AUDIO_FILE,FILE_METADATA'
    logger.warning(f"Calling {u}\n")
    r = requests.get(u, headers={'Accept': 'application/json'}, verify=False)
    if r.status_code != 200:
        logger.error(f"Return code: {r.status_code}\n")
        sys.exit(2)
    r = json.loads(r.content)

    urls = set()
    for file in r.get("files", []):
        if file.get("type") != "AUDIO":
            continue
        for metadata in file.get("metadata", []):
            if metadata.get("key") in ("tag", "av:tag") and metadata.get("value") in shape_tags:
                for location in file.get("fileLocations", []):
                    url = location.get("url")
                    if url:
                        urls.add(url)
    for url in urls:
        if REPLACE_URL:
            try:
                i = url.index("/APInoauth/")
                url = f"{REPLACE_URL}{url[i:]}"
            except ValueError:
                pass

        u = f"{ANALYZE_URL}/analyze/audio/async?url={quote_plus(url)}"
        logger.warning(f"Calling {u}\n")
        r = requests.get(u, headers={"Accept": "application/json"}, verify=False)
        if r.status_code != 200:
            logger.error(f"Return code: {r.status_code}\n")
            sys.exit(3)