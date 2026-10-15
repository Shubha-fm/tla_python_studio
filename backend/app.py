import os
from flask import Flask,request,jsonify,send_from_directory
from flask_cors import CORS
from tla_parser import tla_to_python_from_string,TranslationError
from verification import verify
from tlc_runner import tlc_status, run_tlc
ROOT=os.path.dirname(os.path.abspath(__file__))
FRONTEND=os.path.join(ROOT,'..','frontend','build')
app=Flask(__name__,static_folder=FRONTEND,static_url_path='/')
CORS(app,origins=os.environ.get('CORS_ORIGINS','http://localhost:3000').split(','))
app.config['MAX_CONTENT_LENGTH']=250000
@app.get('/api/health')
def health():return jsonify(ok=True,service='TLA+ Python Studio',version='2.0')
@app.post('/api/convert')
def convert():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify(ok=False,error='Provide a JSON object.'),400
    if data.get('mode','tla')!='tla':return jsonify(ok=False,error='Lean conversion is not implemented.'),422
    try:return jsonify(ok=True,output=tla_to_python_from_string(data.get('code','')),warnings=['Restricted TLA+ subset only. Not a TLC replacement.'])
    except (TranslationError,ValueError) as e:return jsonify(ok=False,error=str(e)),422
@app.post('/api/verify')
def verification():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify(ok=False,error='Provide a JSON object.'),400
    try:return jsonify(ok=True,**verify(data.get('code',''),data.get('property',''),data.get('max_depth',12),data.get('max_states',120)))
    except (TranslationError,ValueError,SyntaxError,TypeError) as e:return jsonify(ok=False,error=str(e)),422
@app.get('/api/tlc/status')
def tlc_availability():return jsonify(ok=True,**tlc_status())
@app.post('/api/tlc/run')
def tlc_run():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify(ok=False,error='Provide a JSON object.'),400
    try:return jsonify(ok=True,**run_tlc(data.get('code',''),data.get('invariant','')))
    except (TranslationError,ValueError) as e:return jsonify(ok=False,error=str(e)),422
@app.get('/')
def index():return send_from_directory(FRONTEND,'index.html')
@app.get('/<path:path>')
def static_files(path):
    if path.startswith('api/'):return jsonify(error='Not found'),404
    file=os.path.join(FRONTEND,path)
    return send_from_directory(FRONTEND,path if os.path.isfile(file) else 'index.html')
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT','5050')),debug=os.environ.get('FLASK_DEBUG')=='1')
