#!/usr/bin/python3
# script version and log level
script_version = "241215.10"
log_level = "INFO" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Item ID
2. Vantage workflow name
3. Audio profile number (optional)
4. 'manual' (optional)
5. Environment

WHAT THE SCRIPT DOES:
-Imports an external config file of Vantage workflow names, IDs, and requirements
-Checks to see if item is a placeholder; if so, sends BBQ Complete call and ends
-If 'manual' is one of the arguments, stamps file_information_queue_avoidance = True
-Checks the config file for the given workflow
    -If "profile_required" = True, checks the arguments for audio profile number
        -If profile number indicates bad audio, stamps Audio and Aggregate test results "Completed" and "Fail" and ends
    -If the item is golden, checks metadata for existing profile number and uses that instead
-Checks metadata for subtype info (mezz/deriv) and md5 value
-Pulls shape data
-Makes sure the item's shape has a local file; tries to download from VOD Library or S3 bucket if not
    -Sends BBQ Complete call if not 'manual'
-Checks config file for the required shape tag
   -Gets shape ID, local storage ID, and local file path from shape data for the tagged shape
-Checks config file for workflow ID
-Gets latest version numbers from master_vantage_versions.xml
-Gets workflow-specific Job Input object from Vantage
    -a JSON-formatted dictionary that tells us which media files, label data, and variable values Vantage needs for a given workflow
-Populates all relevant fields within the Job Input dictionary
    -File path was assigned earlier
    -Variables are populated from their corresponding VS metadata field values
-POSTs a job-submit call to Vantage with the Job Inputs dictionary in the body of the call
'''

###CHANGE LOG###
'''
version 241215.10 - initial version
'''

# native imports
import sys # argv, platform, stdout
import json
import os
from urllib.parse import unquote

import requests
requests.packages.urllib3.disable_warnings()

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
if len(sys.argv) > 6:
    arg_problem = "Too many args provided!"
elif len(sys.argv) < 3:
    arg_problem = "Not enough args provided!"
else:
    # item id and workflow
    script_name =  cms_integration_logging.get_script_name(sys.argv[0])
    item_id = sys.argv[1]
    workflow_name = sys.argv[2]

    # manual (optional)
    if 'manual' in sys.argv:
        manual_submit = True
    else:
        manual_submit = False

    # audio profile (optional)
    profile_number = False
    profile_numbers = 0
    for i in range(len(sys.argv)):
        if sys.argv[i].isnumeric():
            profile_number = sys.argv[i]
            profile_numbers += 1
    if profile_numbers > 1:
        arg_problem = "Bad arguments provided! Too many numbers."

    # env (could be anywhere in args)
    if 'UAT' in sys.argv or 'uat' in sys.argv:
        env = 'uat'
    elif 'DEV' in sys.argv or 'dev' in sys.argv:
        env = 'dev'
    else:
        env = 'prod'    # default

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
logger.info(f'{workflow_name} provided as the target workflow.', extra=extras)
logger.info(f'manual submit is set to {str(manual_submit)}.', extra=extras)
if profile_number:
    logger.info(f'{profile_number} provided as audio profile number.', extra=extras)

# project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# dictionary for reference
import vantage_profiles

# custom functions
def submit_to_vantage(vs,vs_token_data,bbq_data,vantage):

    shapes = {}
    if env == 'uat':
        profiles = vantage_profiles.uat
        download_locations = ['VX-111','VX-9']
    elif env == 'dev':
        profiles = vantage_profiles.dev
        download_locations = ['VX-146','VX-18']
    elif env == 'prod':
        profiles = vantage_profiles.production
        download_locations = ['VX-143','VX-266']

    status_file = f'{os.path.dirname(script_path)}/{env}_pending_downloads.txt'
    workflow = profiles[workflow_name]
    # can't use 'api_url' secret because we don't want the port
    bbq_complete = f"{bbq_data['protocol']}://{bbq_data['host']}/bbq/api/jobs/complete/"

    logger.warning(f'{item_id} Submitted to {workflow_name}')

    # placeholder check
    is_placeholder = eng_vs_token.get_system_metadata_value(vs_token_data,item_id,'__placeholder_shape_size')
    if is_placeholder == '1':
        logger.warning('Item is placeholder, marking complete.')
        payload = {'item_id': item_id}
        headers = {'content-type': 'application/json'}
        r = requests.post(bbq_complete, headers=headers, data=json.dumps(payload))
        logger.warning(f'BBQ Complete status code: {r}')
        return True

    if manual_submit:
        vs_group,vs_field,vs_value = 'file_information','file_information_queue_avoidance','True'
        metadata = eng_vs_token.make_group_metadata_doc(vs_group,vs_field,vs_value)
        u = eng_vs_token.put_item_metadata(vs_token_data,item_id,metadata)
        logger.warning('Stamping Queue Avoidance as True')
        logger.warning(f'Update status code: {u}')

    subtype = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,'file_information_subtype')

    if workflow['profile_required']:
        global profile_number
        if str(profile_number) in ['999','998']:
            eng_vs_token.handle_bad_audio(vs_token_data, item_id, profile_number, env)
            return True
        golden_child = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,'file_information_is_golden_child')
        if golden_child == 'True':
          if 'deriv' in subtype.lower():
            profile_number = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,'deriv_qc_orig_audio_profile_number')
          else:
            profile_number = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,'mezz_qc_orig_audio_profile_number')

    md5 = eng_vs_token.get_md5(vs_token_data,item_id)

    # check for local shape
    shape = workflow['required_shapes'][0]
    logger.warning(f'Checking for {shape} shape presence')
    # get_shape_ids and get_storage_group return lists
    shape_id = eng_vs_token.get_shape_ids(vs,vs_token_data['token'],item_id,shape)[0]
    logger.warning(f'{shape} shape id {shape_id}')
    shape_document = eng_vs_token.get_shape_document(vs,vs_token_data['token'],item_id,shape)
    local_storage = eng_vs_token.get_storage_groups(vs_token_data,'local')
    shape_location = eng_vs_token.current_storage_id(vs_token_data,item_id,local_storage,shape)
    cloud_storage = eng_vs_token.get_storage_groups(vs_token_data,'cloud')
    library_storage = eng_vs_token.get_storage_groups(vs_token_data,'library')

    if shape_location == False and shape == 'original':
        logger.warning('Download Required')
        structured = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,'media_management_structured_path')
        if structured:
            download_location = download_locations[0]
        else:
            download_location = download_locations[1]
        original_filename = eng_vs_token.get_system_metadata_value(vs_token_data,item_id,'originalFilename')
        try:
            download_job = eng_vs_token.download_from_s3(vs_token_data, shape_document, download_location, library_storage, item_id, original_filename)
        except Exception as e:
            logger.error(f'Error downloading from Library {e}')
            try:
                download_job = eng_vs_token.download_from_s3(vs_token_data, shape_document, download_location, cloud_storage, item_id, original_filename)
            except Exception as e:
                logger.error(f'Error downloading from Cloud {e}')
                exit(1)

        if download_job:
            logger.warning(f'Started s3 Download - Job ID: {download_job}')
            if not os.access(status_file, os.W_OK):
                logger.warning('Unable to write to Status File')
                return True
            with open(status_file,'a') as f:
              f.write(f'{download_job}\n')
              f.close()
            if not manual_submit:
                payload = {'item_id': item_id}
                headers = {'content-type': 'application/json'}
                r = requests.post(bbq_complete, headers=headers, data=json.dumps(payload))
                logger.warning(f'Marked Complete in BBQ. Status code {r}')
            return True
        else:
            logger.warning('S3 Download still in progress')
            # tell bbq
            if not manual_submit:
                payload = {'item_id': item_id}
                headers = {'content-type': 'application/json'}
                r = requests.post(bbq_complete, headers=headers, data=json.dumps(payload))
                logger.warning(f'Marked Complete in BBQ. Status code {r}')
            return True
    elif shape_location == None:
        logger.warning(f'{shape} shape is missing and is not backed up to s3! please resubmit to file info')
        return False


    for index, shape in enumerate(workflow['required_shapes']):
        shape_id = eng_vs_token.get_shape_ids(vs,vs_token_data['token'],item_id,shape)[0]
        shape_document = eng_vs_token.get_shape_document(vs,vs_token_data['token'],item_id,shape)
        shape_location = eng_vs_token.current_storage_id(vs_token_data,item_id,local_storage,shape)
        file_uri = shape_document.find(f'shape/*[1]/file[storage="{shape_location}"]/uri').text
        windows_path = file_uri.replace('file:///mnt/','').split('/')
        if windows_path[0].lower() == 'xdrive':
            windows_path[0] = '\\\\vc67.vcnyc.indemand.net\\vodstorage'
            windows_path = '\\'.join(windows_path)
        elif windows_path[0].lower() == 'mezz':
            windows_path[0] = 'M:'
            windows_path = '\\'.join(windows_path)
        shapes[index] = {'name':shape,'shape_id':shape_id,'shape_document':shape_document,'current_storage':shape_location,'windows_path':unquote(windows_path)}
        logger.warning(f'Windows path {windows_path}')
        logger.warning(f'Shapes {shapes}')

    extracted_audio_shape_presence = eng_vs_token.shape_presence(vs_token_data,item_id,'extracted_audio')
    s3_copy_presence = eng_vs_token.storage_presence(vs_token_data,item_id,cloud_storage)
    wid = profiles[workflow_name]['wid']

    looking_for = shapes[0]['current_storage']
    file_uri = shapes[0]['shape_document'].find(f'shape/*[1]/file[storage="{looking_for}"]/uri').text
    file_id = shapes[0]['shape_document'].find(f'shape/*[1]/file[storage="{looking_for}"]/id').text

    job_inputs = json.loads(requests.get(f'{vantage}REST/Workflows/{wid}/JobInputs',verify=False).content)

    # implement new versions doc
    versions = 'M:\\ADMIN\\Vantage\\Vantage_Version_Attachment\\master_vantage_versions.xml'

    logger.warning('Loaded Job Inputs')

    job_inputs['JobName'] = f"{workflow['name']}_{item_id}"

    if workflow['versions']:
        job_inputs['Attachments'][0]['File'] = fr'{versions}'

    logger.warning('Added Versions')

    for shape in shapes:
        job_inputs['Medias'][shape]['Files'][0] = rf"{shapes[shape]['windows_path']}"

    logger.warning('Added Shapes')

    priority = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,'indab_vantage_priority')

    if priority and priority.lower() == 'true':
        job_inputs['Priority'] = 100
    try:
        for variable in job_inputs['Variables']:
            temp_value = eng_vs_token.get_system_metadata_value(vs_token_data,item_id,variable['Description'])
            temp_value_2 = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,variable['Description'])
            if temp_value:
                if temp_value != 0:
                    variable['Value'] = temp_value
            elif temp_value_2:
                variable['Value'] = temp_value_2
            elif variable['Description'] == 'audio_shape_presence':
                variable['Value'] = extracted_audio_shape_presence
            elif variable['Description'] == 'shape_id':
                variable['Value'] = shapes[0]['shape_id']
            elif variable['Description'] == 'downmix_analysis_audio':
                variable['Value'] = shapes[1]['shape_id']
            elif variable['Description'] == 'file_id':
                variable['Value'] = file_id
            elif variable['Description'] == 's3_copy_presence':
                variable['Value'] = str(s3_copy_presence).capitalize()
            elif variable['Description'] == 'md5':
                variable['Value'] = md5
            elif variable['Description'] == 'storage_id':
                variable['Value'] = shapes[0]['current_storage']
            elif variable['Description'] == 'ats_profile_number':
                variable['Value'] = profile_number
            elif variable['Description'] == 'vantage_server_ip':
                variable['Value'] = vs
            else:
                variable['Value'] = variable['DefaultValue']
    except Exception as e:
        logger.warning('Unable to fill job inputs')
        logger.warning(e)

    r = requests.post(f'{vantage}REST/Workflows/{wid}/Submit',headers={'content-type':'application/json'},data=json.dumps(job_inputs),verify=False)
    results = json.loads(r.content)
    if results['JobIdentifier'] == "00000000-0000-0000-0000-000000000000":
        logger.warning(f'SDK Error {item_id}')
        logger.warning(job_inputs)
        return False

    logger.warning(f'Submitted {item_id} to {workflow_name}')
    logger.warning(f'Response {r.content}')

    return True

if __name__ == "__main__":
    # get_vault_secret_data function returns a dict
    # vidispine
    vidi_path = f'v1/secret/{env}/vidispine/vantage'
    vs_secret_data = eng_vault_agent.get_secret(vidi_path)
    vs_username = vs_secret_data["username"]
    vs_password = vs_secret_data["password"]
    vs = vs_secret_data["api_url"]
    seconds = 60
    vs_basic_auth = eng_vs_token.get_basic_auth(vs_username,vs_password)
    vs_token_data = eng_vs_token.get_token_no_auto_refresh(vs,vs_basic_auth,seconds)
    if not vs_token_data:
        logger.error("Didn't get token data from vidispine?")
        exit(2)

    # bbq
    bbq_data = {}
    bbq_path = f'v1/secret/{env}/bbq/vantage'
    bbq_secret_data = eng_vault_agent.get_secret(bbq_path)
    bbq_data['host'] = bbq_secret_data['host']
    bbq_data['protocol'] = bbq_secret_data['protocol']
    bbq_data['token'] = bbq_secret_data['token']

    # vantage
    vantage_path = f'v1/secret/{env}/vantage/vantage'
    vantage = eng_vault_agent.get_secret(vantage_path)['api_url']

    # here we go
    s = submit_to_vantage(vs,vs_token_data,bbq_data,vantage)
    if s:
        exit(0)
    else:
        exit(1)
