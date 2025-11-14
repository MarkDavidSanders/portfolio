#!/usr/bin/python3
# script version and log level
script_version = "250115.14"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

'''
Due to the way arguments are handled here, we need to do things in a slightly different order than usual.

ARGUMENTS RECEIVED FROM VANTAGE:
1. Item ID
2. Up to four languages, one per audio stream (optional)
3. "manual" (optional)
3. Environment

WHAT THE SCRIPT DOES:
-Imports Nexidia language-code dictionary
-Logs "manual" if "manual"
-Gets subtype from Vidispine
-If no languages in argument, gets accurate_player_language_profile_description value from Vidispine
-If language in argument is 2 characters long (i.e. a Nexidia code), cross-checks Nexidia dict for full name of language
  -If argument is "enm", translates that to "dvs"
-Associates each language in arguments/profile_description field with an audio track
  -First lang is paired with first track, second with second, etc.
-Using Nexidia dict as reference, conforms each language code to ISO639_1 standard
-Builds metadata fields
  -Mezz/deriv_qc_orig_language_profile
  -Mezz/deriv_qc_orig_language_profile_track_1/2/3/4_summary
  -If manual: Mezz/deriv_qc_orig_language_profile_manual_submit = True
    -And Mezz/deriv_qc_orig_language_profile_nexidia_job = 'Manual entry by engineering'
  -Mezz/deriv_qc_orig_language_profile_number
  -Mezz/deriv_qc_orig_language_profile_description
-Stamps item with all fields
'''

###CHANGE LOG###
'''
version 250115.14 - initial version
'''

# native imports
import sys
import requests
import xml.etree.ElementTree as ET

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

# arg problem (handling comes later)
arg_problem = False
if len(sys.argv) > 8:
  arg_problem = "Too many args provided!"
elif len(sys.argv) < 3:
  arg_problem = "Not enough args provided!"

# args needed for logging
script_name = cms_integration_logging.get_script_name(sys.argv[0])
item_id = sys.argv[1]
# env could be anywhere in args
if 'UAT' in sys.argv or 'uat' in sys.argv:
  env = 'uat'
elif 'DEV' in sys.argv or 'dev' in sys.argv:
  env = 'dev'
else:
  env = 'prod'    # default
for x in ['dev','DEV','uat','UAT','prod','PROD']:
  if x in sys.argv:
    sys.argv.remove(x)

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

logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'{item_id} provided as the item.', extra=extras)

# project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# dictionary for reference
from nexidia_codes import nexidia_codes as nexidia

# indemand secretssssssssss
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

# language code translator function
def iso_translate(languages,target_language):
  for key in languages:
    if languages[key]['iso6391'] == target_language:
      return key
  return 'not_present'

# here we go
logger.warning('Starting Manual Language Metadata Update')

subtype = eng_vs_token.get_group_metadata_value(token_data,item_id,'file_information_subtype')
if 'mezzanine' in subtype.lower():
  subtype = 'mezz'
elif 'derivative' in subtype.lower():
  subtype = 'deriv'
else:
  logger.warning(f'Unable to determine subtype for {item_id}')
  exit(1)

# manual + language args
if 'manual' in sys.argv:
    manual = True
    logger.info(f'Manual submit.')
    sys.argv.remove('manual')
    corrected_args = []
    for arg in sys.argv[1:]:
        splits = arg.split(',')
        for s in splits:
            corrected_args.append(s)
    logger.warning(f'{corrected_args[1:]} provided as language argument(s).')
    sys.argv = [sys.argv[0]] + corrected_args
else:
  manual = False

# if no lang in args, check metadata
if sys.argv[2] == '':
  sys.argv[2] = eng_vs_token.get_group_metadata_value(token_data,item_id,'accurate_player_language_profile_description')
  if sys.argv[2] is None:
    logger.warning('No languages found in arguments or item metadata. Sad!')
    exit(0)

languages = []

for arg in sys.argv[2:]:
  if arg == 'un' or arg == 'not available':
    languages.append('unknown')
  elif len(arg) == 2:
    languages.append(iso_translate(nexidia,arg).lower())
  elif arg == 'enm':
    languages.append('dvs')
  else:
    languages.append(arg.lower())

while len(languages) < 4:
  languages.append('not_present')

track_one, track_two, track_three, track_four = {},{},{},{}
tracks = [track_one,track_two,track_three,track_four]

iso_codes = ['ISO639_1','ISO639_2B','ISO639_2T','engname']

for num in range(0,4):
  track = tracks[num]
  language = languages[num]
  track['lang'] = language
  track['profile'] = nexidia[language]['profile_number']
  track['ISO639_2B'] = nexidia[language]['iso6392b']
  track['ISO639_2T'] = nexidia[language]['iso6392t']
  track['ISO639_1'] = nexidia[language]['iso6391']
  track['engname'] = track['lang'].capitalize()
  track['summary'] = f'The spoken language on track {str(num + 1)} is {language.capitalize()} ({track["ISO639_1"]})'

tracks_string = f'{track_one["profile"]}.{track_two["profile"]}.{track_three["profile"]}.{track_four["profile"]}'

# construct metadata document
metadata_update = ET.Element('MetadataDocument')
metadata_update.attrib['xmlns'] = 'http://xml.vidispine.com/schema/vidispine'
timespan = ET.SubElement(metadata_update,'timespan')
timespan.attrib['end'] = '+INF'
timespan.attrib['start'] = '-INF'
language_profile_group = ET.SubElement(timespan,'group')
language_profile_name = ET.SubElement(language_profile_group,'name')
language_profile_name.text = f'{subtype}_qc_orig_language_profile'

for track in enumerate(tracks,start=1):
  if track[1]['lang'] != 'not_present':
    field = ET.SubElement(language_profile_group,'field')
    name = ET.SubElement(field,'name')
    name.text = f'{subtype}_qc_orig_language_profile_track_{track[0]}_summary'
    value = ET.SubElement(field,'value')
    value.text = track[1]['summary']

if manual:
  manual_submit_field = ET.SubElement(language_profile_group,'field')
  manual_submit_name = ET.SubElement(manual_submit_field,'name')
  manual_submit_name.text = f'{subtype}_qc_orig_language_profile_manual_submit'
  manual_submit_value = ET.SubElement(manual_submit_field,'value')
  manual_submit_value.text = 'True'
  nexidia_field = ET.SubElement(language_profile_group,'field')
  nexidia_name = ET.SubElement(nexidia_field,'name')
  nexidia_name.text = f'{subtype}_qc_orig_language_profile_nexidia_job'
  nexidia_value = ET.SubElement(nexidia_field,'value')
  nexidia_value.text = 'Manual entry by engineering'

profile_number_field = ET.SubElement(language_profile_group,'field')
profile_number_name = ET.SubElement(profile_number_field,'name')
profile_number_name.text = f'{subtype}_qc_orig_language_profile_number'
profile_number_value = ET.SubElement(profile_number_field,'value')
profile_number_value.text = tracks_string

profile_description_field = ET.SubElement(language_profile_group,'field')
profile_description_name = ET.SubElement(profile_description_field,'name')
profile_description_name.text = f'{subtype}_qc_orig_language_profile_description'
profile_description_value = ET.SubElement(profile_description_field,'value')
profile_description_value.text = tracks[0]['ISO639_2B']
for track in tracks[1:]:
  if track['lang'] != 'not_present':
    profile_description_value.text += f' {track["ISO639_2B"]}'

audio_analysis_group = ET.SubElement(timespan,'group')
audio_analysis_name = ET.SubElement(audio_analysis_group,'name')
audio_analysis_name.text = f'{subtype}_qc_orig_audio_analysis'

for track in enumerate(tracks,start=1):
  if track[1]['lang'] != 'not_present':
    for code in iso_codes:
      field = ET.SubElement(audio_analysis_group,'field')
      name = ET.SubElement(field,'name')
      name.text = f'{subtype}_qc_orig_audio_analysis_track_{track[0]}_language_{code}'
      value = ET.SubElement(field,'value')
      value.text = track[1][code]

headers = {'content-type': 'application/xml'}
u = eng_vs_token.put_item_metadata(token_data,item_id,ET.tostring(metadata_update))

logger.warning(f'Metadata Update Response Code: {u}')
logger.warning('Ending Metadata Update')
exit(0)