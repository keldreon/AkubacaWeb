from flask import Flask, request, render_template
import os   
import logging
from azure.storage.blob import BlobServiceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.ai.textanalytics import TextAnalyticsClient
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static', static_url_path='')  

handler = logging.FileHandler('test.log') # creates handler for the log file
app.logger.addHandler(handler) # adds handler to the werkzeug WSGI logger
app.logger.setLevel(logging.DEBUG)         # Set the log level to debug


app.config.from_pyfile('config.py')

#azure access to container
connect_str = app.config['CONNECTION_STRING'] # retrieve the connection string from the environment variable
container_nm = app.config['CONTAINER'] # container name in which images will be store in the storage account
key = app.config['ACCOUNT_KEY']

allowed_ext = app.config['ALLOWED_EXTENSIONS']
max_length = app.config['MAX_CONTENT_LENGTH']

#azure acccess to cognition
congnition_endpoint = app.config['VISION_ENDPOINT']
congnition_sm = app.config['VISION_KEY']

#azure access to summarizzer resource
summarizer_endpoint = app.config['SUMMARIZE_URL']
summarizer_sm = app.config['SUMMARIZE_SECRET']

#azure access to translation resource
translation_endpoint = app.config['TRANSLATION_URL']
translation_sm = app.config['TRANSLATION_SECRET']
translation_region = app.config['TRANSLATION_REGION']


blob_service_client = BlobServiceClient.from_connection_string(connect_str) # create a blob service client to interact with the storage account

#authenticate azure cognitive
def img_authenticate_client():
    ta_credential = AzureKeyCredential(congnition_sm)
    img_analytics_client = ImageAnalysisClient(
            endpoint=congnition_endpoint, 
            credential=ta_credential)
    return img_analytics_client

#authenticate azure summarizer
def summarizer_authenticate_client():
    ta_credential = AzureKeyCredential(summarizer_sm)
    text_analytics_client = TextAnalyticsClient(
            endpoint=summarizer_endpoint, 
            credential=ta_credential)
    return text_analytics_client

#authenticate azure ai translator
def translator_authenticate_client():
    from azure.ai.translation.text import TextTranslationClient, TranslatorCredential

    endpoint = translation_endpoint
    apikey = translation_sm
    region = translation_region
    # [START create_text_translation_client_with_credential]
    credential = TranslatorCredential(apikey, region)
    text_translator = TextTranslationClient(credential=credential, endpoint=endpoint)
    # [END create_text_translation_client_with_credential]
    return text_translator

#generate sas to access file inside storage blob
def generate_sas(fpath, container_name):
    from datetime import datetime, timedelta
    from azure.storage.blob import BlobServiceClient, generate_blob_sas, ResourceTypes, BlobSasPermissions

    #head, filename = os.path.split(fpath) #split blob and file name
    sas_token = generate_blob_sas(
        account_name=app.config['ACCOUNT_NAME'],
        account_key= app.config['ACCOUNT_KEY'],
        container_name="img-trigger",
        blob_name=fpath,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(hours=1)
    )
    url_img = f'https://tesocr.blob.core.windows.net/{container_name}/{fpath}?{sas_token}'
    return url_img

# azure translator, default: source "en" and target language in Indonesia.
def ai_translate_txt(client, document, source_lang="en", target_lang=["id"]):
    from azure.ai.translation.text import TextTranslationClient
    from azure.core.credentials import AzureKeyCredential
    from azure.ai.translation.text.models import InputTextItem
    
    translated_text = ""
    source_language = source_lang
    target_languages = target_lang
    input_text_elements = [ InputTextItem(text = document) ]

    response = client.translate(
        content=input_text_elements, to=target_languages, from_parameter=source_language
    )
        
    translation = response[0] if response else None

    if translation:
        for translated_txt in translation.translations:
            translated_text += "\n{}".format(
            " ".join([translated_txt.text]))
            app.logger.info(f"Text was translated to: '{translated_txt.to}' and the result is: '{translated_txt.text}'.")
   
    return translated_text

# method for  extract text from img
def ai_extract_txt(client, document):
    from azure.ai.vision.imageanalysis import ImageAnalysisClient
    from azure.ai.vision.imageanalysis.models import VisualFeatures
    #print(document)
 
    result = client.analyze(
        image_data = document,
        visual_features=[VisualFeatures.READ]
    )

    extracted_text = ""
   
    if result.read is not None:
        for line in result.read.blocks[0].lines:
            extracted_text += "\n{}".format(" ".join([line.text]))
    
    app.logger.info(f"Returning OCR extraction text:  \n{extracted_text}")     
    return extracted_text

# summarizer
def ai_summarize_txt(client, document, sum_size=10):
    from azure.ai.textanalytics import (
        TextAnalyticsClient,
        ExtractiveSummaryAction
    ) 
    poller = client.begin_analyze_actions(
        document,
        actions=[
            ExtractiveSummaryAction(max_sentence_count=sum_size)
        ],
    )
    summarized_text = ""
    document_results = poller.result()
    for result in document_results:
        extract_summary_result = result[0]  # first document, first result
        if extract_summary_result.is_error:
            app.logger.info("...Is an error with code '{}' and message '{}'".format(
                extract_summary_result.code, extract_summary_result.message
            ))
        else:
            summarized_text += "Summary extracted: \n{}".format(
                " ".join([sentence.text for sentence in extract_summary_result.sentences]))
            app.logger.info(f"Returning summarized text:  \n{summarized_text}")
    return summarized_text

#index
@app.route("/")  
def index():  
    return render_template("index.html")

#result page route
@app.route("/result")
def result():
    return render_template('result.html')

#flask endpoint to upload a photo  
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_ext

#allowed photos document
@app.route("/upload-photos", methods=["POST"])  
def upload_photos():  
    filenames = ""
    pesan = ""
    sum_rtxt = []
    translated_rtxt = []
    if 'file' in request.files:
        img = request.files['file']
        if img and allowed_file(img.filename):
            fname = secure_filename(img.filename)  #get filename
            img.save(fname) 
            #authenticate each client

            #blob_client = blob_service_client.get_blob_client(container = container_nm, blob = fname)
            cognito_client = img_authenticate_client() 
            sum_client = summarizer_authenticate_client()
            translator_client = translator_authenticate_client()

            with open(fname, "rb") as data:
                image_data = data.read()
                try:
                    extracted_txt = ai_extract_txt(cognito_client, image_data) #extract text from image
                    sum_rtxt = ai_summarize_txt(sum_client, [extracted_txt]) #summarizer
                    #blob_client.upload_blob(data, overwrite=True) # upload the file to the container using the filename as the blob name
                    translated_rtxt = ai_translate_txt(translator_client, sum_rtxt) #translate summarizer result
                    pesan = translated_rtxt #pesan in english is message, so lets input result of translated summarizer as message to show in result
                except:
                    pass     
            os.remove(fname) #remove file name
    return render_template("result.html", msg=pesan)

