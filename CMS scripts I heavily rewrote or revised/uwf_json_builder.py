#!/usr/bin/python3
# script version and log level
script_version = "250127.13"
log_level = "INFO" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Item ID
2. Environment

WHAT THIS SCRIPT DOES:
-Builds JSON object of UWF Validation test results, populating each sub-section with the item's metadata field values
-Returns three JSON objects to Vidispine as item's field values
  -file_information_uwf_validation_json_video
  -file_information_uwf_validation_json_audio
  -file_information_uwf_validation_json_text
'''
###CHANGE LOG###
'''
version 250127.13 - initial version
'''

#native imports
import json
import xml.etree.ElementTree as ET
import sys
import requests
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
def media_info_property(shape,target_component,target_property,audio=False):
  try:
    if audio:
      return shape.find(f'shape/{target_component}Component[itemTrack="A{audio}"]/mediaInfo/property[key="{target_property}"]/value').text
    else:
      return shape.find(f'shape/{target_component}Component/mediaInfo/property[key="{target_property}"]/value').text
  except:
    return None

def get_section(report,target_section):
  for index, section in enumerate(report['uwf_report']['section']):
    if report['uwf_report']['section'][index]['_name'] == target_section:
      return report['uwf_report']['section'][index]

def build_json(vs_token_data, item_id):
  vs = vs_token_data['vs']
  token = vs_token_data['token']
  shape = eng_vs_token.get_shape_document(vs, token, item_id, 'original')
  shape_id = shape.find('shape/id').text

  if shape.find('shape/containerComponent/mediaInfo') == None:
    headers = {
			'Content-Type': 'application/xml',
			'Authorization': f'token {token}'
		}
    r = requests.post(f'{vs}API/item/{item_id}/shape/{shape_id}/update?priority=HIGHEST', headers=headers)
    if r.status_code == 200:
      logger.warning('No mediainfo properties found, updating shape')
      return False
    else:
       logger.warning(f'Shape update status code {r.status_code}. Quitting')
       exit(1)

  logger.warning(f'Building UWF JSON for {item_id}')

  file_name = eng_vs_token.get_system_metadata_value(vs_token_data, item_id, 'originalFilename')
  validation_descriptor = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'file_information_uwf_profile_description')
  md5_checksum = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'original_shape_mi_original_shape_mi_md5_hash')

  raw_bit_rate = media_info_property(shape,'container','Overall bit rate')
  overall_bit_rate = f'{str(round(float(raw_bit_rate)/1000000.00,2))} Mb/s'

  uwf_profile_number = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'file_information_uwf_profile_number')
  uwf_profile_result = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'file_information_uwf_profile')

  # Validation Tests
  if uwf_profile_result == 'True':
    uwf_profile_match = 'PASS'
    uwf_profile_description = f'{validation_descriptor} (Engineering UWF Profile # {uwf_profile_number})'
  elif uwf_profile_result == 'False':
    uwf_profile_match = 'FAIL'
    uwf_profile_description = 'The properties listed in MediaInfo did not match an approved UWF profile or we do not have the correct data.'
  else:
    uwf_profile_match = 'FAIL'
    uwf_profile_description = 'This asset did not complete UWF Validation testing.'

  uwf_vendor_result = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'file_information_uwf_vendor_match')
  possible_studio = str(eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'file_information_uwf_possible_studio')).replace('_',',')
  vendor_folder = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'file_information_vendor_folder')

  if uwf_vendor_result == 'True':
    uwf_vendor_match = 'PASS'
    uwf_vendor_description = f'This asset arrived and was imported in an expected vendor aspera folder ({vendor_folder}) for the media properties format (Engineering UWF Profile #{uwf_profile_number}).  Possible studios for the profile include {possible_studio}'
  elif uwf_vendor_result == 'False' and uwf_profile_result == 'True':
    uwf_vendor_match = 'PASS WITH WARNING'
    uwf_vendor_description = f'This asset was not imported into the CMS from an expected vendor aspera folder for the discovered UWF Profile type (#{uwf_profile_number}).  It may still be acceptable for use.'
  else:
    uwf_vendor_match = 'FAIL'
    uwf_vendor_description = 'This asset was not imported into the CMS from an expected vendor aspera folder.'

  aggregate_result = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'aggregate_test_result')

  if 'Pass' in aggregate_result:
    aggregate_result = aggregate_result.upper()
    aggregate_description = 'This asset has passed Engineering QC Testing. See individual results for details.'
  elif 'Fail' in aggregate_result:
    aggregate_result = aggregate_result.upper()
    aggregate_description = 'This asset failed the Engineering QC testing.  Please inspect the QC report.'
  else:
    aggregate_result = 'Unknown'
    aggregate_description = 'This asset may not have been tested or testing was interrupted.'

  # determine validation results
  if uwf_profile_result == 'True' and uwf_vendor_result == 'True' and 'PASS' in aggregate_result:
    validation_result = 'PASS'
  elif uwf_profile_result == 'True' and 'PASS' in aggregate_result:
    validation_result = 'PASS WITH WARNING(S)'
  else:
    validation_result = 'FAIL'

  metadata_update_doc = eng_vs_token.make_group_metadata_doc('file_information', 'file_information_uwf_validation_result', validation_result)
  
  r = eng_vs_token.put_item_metadata(vs_token_data,item_id,metadata_update_doc)
  logger.warning(f'UWF Validation Result metadata update response: {r}')

  # Video
  frame_size = f"{media_info_property(shape,'video','Width')} x {media_info_property(shape,'video','Height')}"
  frame_size_description = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_category_results_framesize_description')

  frame_rate = media_info_property(shape,'video','Frame rate')
  frame_rate_description = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_category_results_framerate_description')

  frame_scan = media_info_property(shape,'video','Scan type')
  frame_scan_description = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_category_results_framescan_description')

  aspect_ratio = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_header_info_aspect_ratio')
  aspect_ratio_description = 'This info is collected from MediaInfo.'

  video_codec = media_info_property(shape,'video','Codec')
  video_format = media_info_property(shape,'video','Format')
  video_format_profile = media_info_property(shape,'video','Format profile')

  if video_codec == 'apch':
    video_codec = f'{video_format} {video_format_profile}'

  video_codec_description = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_category_results_video_codec_description')

  raw_video_bit_rate = media_info_property(shape,'video','Bit rate')
  video_bit_rate = f'{str(round(float(raw_video_bit_rate)/1000000.00,2))} Mb/s'
  video_bit_rate_description = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_category_results_video_bitrate_description')

  # Audio
  number_of_tracks = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_header_info_audio_tracks')

  audio_codec = media_info_property(shape,'audio','Format',audio='1')
  audio_codec_description = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_category_results_audio_codec_description')

  sample_rate = media_info_property(shape,'audio','Sampling rate',audio='1')
  sample_rate_description = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_category_results_audio_samplerate_description')

  audio_configuration = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_audio_profile_description')
  audio_configuration_description = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_category_results_ats_format_vs_codec')

  audio_languages = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_language_profile_description')
  audio_languages_description = 'This is the audio track language configuration derived from analysis.'

  audio_tracks = []

  for track in range(1,int(number_of_tracks) + 1):
    try:
      number_of_channels = media_info_property(shape,'audio','Channel(s)',audio=track)
      audio_bit_rate = media_info_property(shape,'audio','Bit rate',audio=track)
      audio_bit_rate = f'{str(int(audio_bit_rate)/1000)} Kb/s'
      channel_position = media_info_property(shape,'audio','Channel positions',audio=track)
      title = media_info_property(shape,'audio','Title',audio=track)
      language = media_info_property(shape,'audio','Language',audio=track)
      track_info = {'number_of_channels':number_of_channels,'audio_bit_rate':audio_bit_rate,'channel_position':channel_position,'title':title,'language':language}
      audio_tracks.append(track_info)
    except:
      pass

  # Captions
  embedded_caption_count = media_info_property(shape,'container','Count of text streams')
  if embedded_caption_count == None:
    embedded_caption_count = '0'
    embedded_caption_count_description = ''
  else:
    embedded_caption_count_description = media_info_property(shape,'container','Text_Format_List')

  caption_presence = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_category_results_embedded_caption')
  caption_presence_description = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_category_results_embedded_caption_description')

  embedded_caption_quality = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_category_results_timed_text_result')
  embedded_caption_quality_description = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_category_results_timed_text_message')

  external_caption_quality = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_category_results_timed_text_result_ext')
  external_caption_quality_description = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'mezz_qc_orig_category_results_timed_text_message_ext')

  validation_results = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'file_information_uwf_validation_result')

  data = {'uwf_report':{'title':'UWF Validation Report','validation_result':validation_results,'file_name':file_name,'uwf_profile_description':validation_descriptor,'check_sum':md5_checksum,'overall_bit_rate':overall_bit_rate,'section':[{'_name':'UWF Validation Tests'},{'_name':'Video'},{'_name':'Audio'},{'_name':'Captions'}]}}

  # create uwf validation tests section
  uwf_section = get_section(data,'UWF Validation Tests')
  uwf_section['sub_section'] = []

  sub_section = {'field':[],'_name':'Results:'}
  sub_section['field'].append({'_name':'Profile Match:','value':uwf_profile_match,'description':uwf_profile_description})
  sub_section['field'].append({'_name':'Vendor Folder:','value':uwf_vendor_match,'description':uwf_vendor_description})
  sub_section['field'].append({'_name':'Aggregate QC Results:','value':aggregate_result,'description':aggregate_description})

  uwf_section['sub_section'].append(sub_section)

  # create video section
  video_section = get_section(data,'Video')
  video_section['sub_section'] = []

  sub_section = {'field':[],'_name':'Video Details:'}
  sub_section['field'].append({'_name':'Frame Size:','value':frame_size,'description':frame_size_description})
  sub_section['field'].append({'_name':'Frame Rate:','value':frame_rate,'description':frame_rate_description})
  sub_section['field'].append({'_name':'Frame Scan:','value':frame_scan,'description':frame_scan_description})
  sub_section['field'].append({'_name':'Display Aspect Ratio:', 'value': aspect_ratio, 'description': aspect_ratio_description})
  sub_section['field'].append({'_name':'Codec:','value':video_codec,'description':video_codec_description})
  sub_section['field'].append({'_name':'Video Bitrate:','value':video_bit_rate,'description':video_bit_rate_description})

  video_section['sub_section'].append(sub_section)

  # create audio section
  audio_section = get_section(data,'Audio')
  audio_section['sub_section'] = []

  sub_section = {'field':[],'_name':'Overall Audio Details:'}
  sub_section['field'].append({'_name':'Codec (aka format):','value':audio_codec,'description':audio_codec_description})
  sub_section['field'].append({'_name':'Sample Rate:','value':sample_rate,'description':sample_rate_description})
  sub_section['field'].append({'_name':'Analyzed Audio Configuration:','value':audio_configuration,'description':audio_configuration_description})
  sub_section['field'].append({'_name':'Analyzed Audio Language(s):','value':audio_languages,'description':audio_languages_description})

  audio_section['sub_section'].append(sub_section)

  for index,track in enumerate(audio_tracks):
    sub_section = {'field':[],'_name':f'Media Info Audio Track {str(index + 1)} Details:'}
    sub_section['field'].append({'_name':'Number of Channels:','value':track['number_of_channels'],'description':''})
    sub_section['field'].append({'_name':'Audio Bitrate:','value':track['audio_bit_rate'],'description':''})
    sub_section['field'].append({'_name':'Channel Positions:','value':track['channel_position'],'description':''})
    sub_section['field'].append({'_name':'Title:','value':track['title'],'description':''})
    sub_section['field'].append({'_name':'Language','value':track['language'],'description':''})
    audio_section['sub_section'].append(sub_section)

 # create caption section
  caption_section = get_section(data,'Captions')
  caption_section['sub_section'] = []

  sub_section = {'field':[],'_name':'Captions MediaInfo:'}
  sub_section['field'].append({'_name':'Embedded Caption Count:','value':embedded_caption_count,'description':embedded_caption_count_description})

  caption_section['sub_section'].append(sub_section)

  sub_section = {'field':[],'_name':'Captions Presence Analysis:'}
  sub_section['field'].append({'_name':'Presence/Header Agreement:','value':caption_presence,'description':caption_presence_description})

  caption_section['sub_section'].append(sub_section)

  sub_section = {'field':[],'_name':'Captions Quality:'}
  sub_section['field'].append({'_name':'Embedded','value':embedded_caption_quality,'description':embedded_caption_quality_description})
  sub_section['field'].append({'_name':'External','value':external_caption_quality,'description':external_caption_quality_description})

  caption_section['sub_section'].append(sub_section)

  # finalize and send
  report = json.dumps(data)

  report_seg_len = len(report)//3
  report_seg_one = report[:report_seg_len]
  report_seg_two = report[report_seg_len:report_seg_len * 2]
  report_seg_three = report[(report_seg_len * 2):]

  metadata_update_one = eng_vs_token.make_group_metadata_doc('file_information','file_information_uwf_validation_json_video',report_seg_one)
  metadata_update_two = eng_vs_token.make_group_metadata_doc('file_information','file_information_uwf_validation_json_audio',report_seg_two)
  metadata_update_three = eng_vs_token.make_group_metadata_doc('file_information','file_information_uwf_validation_json_text',report_seg_three)
  
  r1 = eng_vs_token.put_item_metadata(vs_token_data,item_id,metadata_update_one)
  logger.warning(f'Video update response: {r1}')
  r2 = eng_vs_token.put_item_metadata(vs_token_data,item_id,metadata_update_two)
  logger.warning(f'Video update response: {r2}')
  r3 = eng_vs_token.put_item_metadata(vs_token_data,item_id,metadata_update_three)
  logger.warning(f'Video update response: {r3}')
  return True

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
      build_json(token_data, item_id)
      exit(0)
    except Exception as e:
      logger.error(traceback.format_exc())
      exit(1)
  else:
    logger.error("Didn't get token data from vidispine?")
    exit(2)