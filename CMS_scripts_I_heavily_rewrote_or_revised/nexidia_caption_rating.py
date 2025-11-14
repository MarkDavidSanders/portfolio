#!/usr/bin/python3
# script version and log level
script_version = "250130.17"
log_level = "INFO" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Item ID
2. Environment

WHAT THIS SCRIPT DOES:
-Gets secrets from Vault
-Gets item's subtype
-Pulls in all fields relating to Nexidia's caption analysis
-Assigns number values to all pass/fail/warning results
-Calculates overall Pass/Pass with WARNING(S)/Fail result based on aggregate number values
-Returns overall results to Vidispine
    -_qc_orig_category_results_timed_text_result
    -_qc_orig_category_results_timed_text_message
'''
###CHANGE LOG###
'''
version 250130.17 - initial version
'''

#native imports
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
def subtype_selector(vs_token_data, item_id):
    subtype = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,'file_information_subtype')
    if 'mezz' in subtype.lower():
        subtype = 'mezz'
    elif 'deriv' in subtype.lower():
        subtype = 'deriv'
    logger.info(f'Subtype {subtype}')
    return subtype

def shift_or_drift_exception():
    rating = 0
    timed_text_result = 'Fail'
    timed_text_message = 'WARNING: Unable to compare closed captions and media. This may be caused by embedding an incorrect scc file or a lack of speech in the media. Please examine this asset. Caption Rating = 0'
    return rating, timed_text_result, timed_text_message

def main(vs_token_data):
    subtype = subtype_selector(vs_token_data, item_id)
    group = f'{subtype}_qc_orig_caption_analysis'
    rating = 2
    timed_text_message = ''
    fails = []

    fields_to_check = {
        'embedded_duration_status': ['embedded_duration_summary', 'Caption Duration.', 5],
        'embedded_line_count_status': ['embedded_line_count_summary', 'Line Count.', 3],
        'embedded_line_length_status': ['embedded_line_length_summary', 'Line Length.', 3],
        'embedded_reading_rate_status': ['embedded_reading_rate_summary', 'Reading Rate.', 5],
        'embedded_incorrect_status': ['embedded_incorrect_summary', 'Incorrect Captions.', 10],
        'embedded_missing_status': ['embedded_missing_summary', 'Missing Captions.', 10]
    }

    shift_result = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,f'{subtype}_qc_orig_caption_analysis_embedded_shift_status')
    shift_summary = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,f'{subtype}_qc_orig_caption_analysis_embedded_shift_summary')

    drift_result = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,f'{subtype}_qc_orig_caption_analysis_embedded_drift_status')
    drift_summary = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,f'{subtype}_qc_orig_caption_analysis_embedded_drift_summary')

    for field in fields_to_check:
        result = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,f'{group}_{field}')
        summary = eng_vs_token.get_group_metadata_value(vs_token_data,item_id,f'{group}_{fields_to_check[field][0]}')
        if str(result) == 'Pass':
            rating += fields_to_check[field][2]
        elif str(result) == 'Fail':
            logger.warning(f'{field} is Failed')
            fails.append(field)
            if 'WARNING:' not in summary:
                new_summary = f'WARNING: {summary}'
            else:
                new_summary = summary
            timed_text_message += f'{fields_to_check[field][1]} '
            update = {group: {'name': f'{group}_{fields_to_check[field][0]}', 'value': new_summary}}
            logger.warning(update)
            update_doc = eng_vs_token.make_group_metadata_doc(group, f'{group}_{fields_to_check[field][0]}', new_summary)
            r = eng_vs_token.put_item_metadata(vs_token_data,item_id,update_doc)
            logger.warning(f'Update response: {r}')

    '''
    Leaving this here for posterity:

    language_group = f'{subtype}_qc_orig_caption_analysis'
    language_status_field = f'{language_group}_embedded_language_status'
    language_criteria_field = f'{language_group}_embedded_language_criteria'
    language_summary = f'{language_group}_embedded_language_summary'

    language_update_one = {language_group: {'name': language_status_field, 'value': 'Pass'}}
    language_update_two = {language_group: {'name': language_criteria_field, 'value': 'Not Tested'}}
    language_update_three = {language_group: {'name': language_summary, 'value': 'Not Tested'}}
 
    for obj in [language_update_one, language_update_two, language_update_three]:
        item.metadata_update(obj)
    '''

    if shift_result == 'Pass':
        rating += 31
    elif shift_result == 'Fail':
        logger.warning('Shift is Failed')
        if 'WARNING:' not in shift_summary:
            new_shift_summary = f'WARNING: {shift_summary}'
        else:
            new_shift_summary = shift_summary
        timed_text_message += 'Shift. '
        shift_update = {group: {'name': f'{group}_embedded_shift_summary', 'value': new_shift_summary}}
        logger.warning(shift_update)
        shift_update_doc = eng_vs_token.make_group_metadata_doc(group, f'{group}_embedded_shift_summary', new_shift_summary)
        r = eng_vs_token.put_item_metadata(vs_token_data,item_id,shift_update_doc)
        logger.warning(f'Update response: {r}')

    if drift_result == 'Pass':
        rating += 31
    elif drift_result == 'Fail':
        logger.warning('Drift is Failed')
        if 'WARNING:' not in drift_summary:
            new_drift_summary = f'WARNING: {drift_summary}'
        else:
            new_drift_summary = drift_summary
        timed_text_message += 'Drift. '
        drift_update = {group: {'name': f'{group}_embedded_drift_summary', 'value': new_drift_summary}}
        logger.warning(drift_update)
        drift_update_doc = eng_vs_token.make_group_metadata_doc(group, f'{group}_embedded_shift_summary', new_drift_summary)
        r = eng_vs_token.put_item_metadata(vs_token_data,item_id,drift_update_doc)
        logger.warning(f'Update response: {r}')

    if shift_result == 'Fail' or drift_result == 'Fail':
        timed_text_result = 'Fail'
        timed_text_message += f'Caption Rating = {rating}'
        timed_text_message = f'WARNING: The following categories failed embedded caption analysis: {timed_text_message}'
    elif len(fails) > 0:
        timed_text_result = 'Pass with WARNING(s)'
        timed_text_message += f'Caption Rating = {rating}'
        timed_text_message = f'WARNING: The following categories failed embedded caption analysis: {timed_text_message}'
    else:
        timed_text_result = 'Pass'
        timed_text_message = f'Embedded captions track(s) are present and contain data. Embedded Caption Rating = {rating}'

    error_messages = ['Test was not executed due to error(s).',
                      'Verification cannot be performed as the captions and the audio belong to different assets.',
                      'Verification cannot be performed as the caption time offset cannot be determined, possibly due to caption and audio belonging to different assets.',
                      'Verification cannot be performed as the caption time offset cannot be determined, due to insufficient dialog data in the beginning.',
                      'Verification cannot be performed as the captions in the sidecar file and media file have different start offset/timelines.']

    if shift_summary in error_messages or drift_summary in error_messages:
        rating, timed_text_result, timed_text_message = shift_or_drift_exception()

    logger.warning(f'Rating: {rating}')
    logger.warning(f'Result: {timed_text_result}')
    logger.warning(f'Message: {timed_text_message}')

    rating_update = {group: {'name': f'{group}_embedded_rating', 'value': str(rating)}}
    logger.warning(rating_update)
    rating_update_doc = eng_vs_token.make_group_metadata_doc(group, f'{group}_embedded_rating', str(rating))
    r = eng_vs_token.put_item_metadata(vs_token_data,item_id,rating_update_doc)
    logger.warning(f'Update response: {r}')

    result_update = {f'{subtype}_qc_orig_category_results': {'name': f'{subtype}_qc_orig_category_results_timed_text_result', 'value': timed_text_result}}
    logger.warning(result_update)
    result_update_doc = eng_vs_token.make_group_metadata_doc(f'{subtype}_qc_orig_category_results', f'{subtype}_qc_orig_category_results_timed_text_result', timed_text_result)
    r = eng_vs_token.put_item_metadata(vs_token_data,item_id,result_update_doc)
    logger.warning(f'Update response: {r}')

    message_update = {f'{subtype}_qc_orig_category_results': {'name': f'{subtype}_qc_orig_category_results_timed_text_message', 'value': timed_text_message.strip()}}
    logger.warning(message_update)
    message_update_doc = eng_vs_token.make_group_metadata_doc(f'{subtype}_qc_orig_category_results', f'{subtype}_qc_orig_category_results_timed_text_message', timed_text_message.strip())
    r = eng_vs_token.put_item_metadata(vs_token_data,item_id,message_update_doc)
    logger.warning(f'Update response: {r}')

    exit(0)

if __name__ == '__main__':
  secret_path = f'v1/secret/{env}/vidispine/vantage'
  vs_secret_data = eng_vault_agent.get_secret(secret_path)
  username = vs_secret_data["username"]
  password = vs_secret_data["password"]
  vs = vs_secret_data["api_url"]
  vs_auth = eng_vs_token.get_basic_auth(username,password)
  auto_refresh = 'false'
  ttl = 60
  token_data = eng_vs_token.get_auto_refresh_token(vs, vs_auth, ttl)
  if token_data:
    try:
      main(token_data)
      exit(0)
    except Exception as e:
      logger.error(traceback.format_exc())
      exit(1)
  else:
    logger.error("Didn't get token data from vidispine?")
    exit(2)