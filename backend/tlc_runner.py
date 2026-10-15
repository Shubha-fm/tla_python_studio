"""Optional bounded-resource TLC runner. Requires Java and a trusted TLC jar installed by operator."""
import os
import re
import subprocess
import tempfile
from pathlib import Path
from tla_parser import TranslationError

def tlc_status():
    jar=os.environ.get('TLC_JAR','')
    enabled=bool(jar and Path(jar).is_file())
    return {'available':enabled,'reason':('TLC jar configured' if enabled else 'TLC_JAR is not configured; install Java and set TLC_JAR to an installed trusted tlc.jar')}

def run_tlc(source,invariant=''):
    status=tlc_status()
    if not status['available']:
        raise TranslationError(status['reason'])
    if not isinstance(source,str) or not source.strip() or len(source)>100000:
        raise TranslationError('TLA+ input must contain between 1 and 100000 characters.')
    if not isinstance(invariant,str) or (invariant and not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',invariant)):
        raise TranslationError('Invariant must be a named TLA+ operator.')
    if not re.search(r'----\s*MODULE\s+Model\s*----',source):
        raise TranslationError('For TLC, name the module Model, matching Model.tla.')
    cfg='INIT Init\nNEXT Next\n'
    if invariant:cfg+='INVARIANT '+invariant+'\n'
    with tempfile.TemporaryDirectory(prefix='studio_tlc_') as d:
        Path(d,'Model.tla').write_text(source,encoding='utf-8')
        Path(d,'Model.cfg').write_text(cfg,encoding='utf-8')
        command=['java','-Xmx256m','-cp',os.environ['TLC_JAR'],'tlc2.TLC','-workers','1','-depth','40','-config','Model.cfg','Model.tla']
        try:
            p=subprocess.run(command,cwd=d,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=25,check=False)
            output=p.stdout[-30000:]
        except FileNotFoundError as exc:raise TranslationError('Java runtime is not installed on the server.') from exc
        except subprocess.TimeoutExpired as exc:raise TranslationError('TLC timed out after 25 seconds. Try a smaller model.') from exc
        return {'engine':'TLC','exit_code':p.returncode,'output':output,'status':'completed' if p.returncode==0 else 'error_or_violation','invariant':invariant,'disclaimer':'TLC results refer to this configuration and model. Review log carefully; successful termination without an invariant is not an invariant proof.'}
