import React,{useState} from 'react';
import Editor from '@monaco-editor/react';
import StateGraph from './StateGraph';

const counter = ["---- MODULE Counter ----","EXTENDS Naturals","VARIABLE count","Init == count = 0","Increment == /\\ count < 3","             /\\ count' = count + 1","Reset == /\\ count = 3","         /\\ count' = 0","Next == Increment \\/ Reset","===="].join('\n');
const pair = ["---- MODULE Pair ----","VARIABLES count, flag","Init == /\\ count = 0","        /\\ flag = TRUE","Step == /\\ count < 2","        /\\ count' = count + 1","        /\\ UNCHANGED flag","Next == Step","===="].join('\n');
function save(content,filename,type='text/plain'){const url=URL.createObjectURL(new Blob([content],{type}));const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
export default function App(){
  const [code,setCode]=useState(counter),[property,setProperty]=useState('count >= 0');
  const [depth,setDepth]=useState(12),[limit,setLimit]=useState(120);
  const [result,setResult]=useState(null),[python,setPython]=useState('');
  const [tab,setTab]=useState('graph'),[selected,setSelected]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [advanced,setAdvanced]=useState(false);
  async function execute(kind){
    setBusy(true);setError('');
    try{
      const response=await fetch('/api/'+kind,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code,property,max_depth:Number(depth),max_states:Number(limit)})});
      const data=await response.json();
      if(!response.ok||!data.ok)throw new Error(data.error||'Request failed');
      if(kind==='convert'){setPython(data.output);setTab('python')}else{setResult(data);setSelected(null);setTab('graph')}
    }catch(err){setError(err.message)}finally{setBusy(false)}
  }
  const status=result?.summary?.property_status||'not_checked';
  return <div className="simple-shell">
    <header className="simple-top"><div className="simple-logo">T+</div><div className="simple-brand"><strong>TLA+ to Python Studio</strong><span>Specification · Conversion · Verification</span></div><a className="simple-gh" href="https://github.com/Shubha-fm/tla_python_studio" target="_blank" rel="noreferrer">GitHub ↗</a></header>
    <main className="simple-main">
      <div className="simple-intro"><h1>Verification workspace</h1><p>Write a model, check a property, and explore its states.</p></div>
      <div className="simple-workspace">
        <section className="simple-card">
          <div className="simple-cardhead"><strong>TLA+ specification</strong><div className="simple-tools"><select aria-label="Example model" defaultValue="" onChange={e=>{setCode(e.target.value==='pair'?pair:counter);setResult(null);setPython('')}}><option value="">Example models</option><option value="counter">Counter</option><option value="pair">Two variables</option></select><label className="simple-upload">Upload<input type="file" accept=".tla,.txt" onChange={async e=>{const file=e.target.files?.[0];if(file){setCode(await file.text());setResult(null);setPython('')}}}/></label></div></div>
          <div className="simple-editor"><Editor language="plaintext" theme="vs-light" value={code} onChange={v=>setCode(v||'')} options={{minimap:{enabled:false},fontSize:13,lineNumbers:'on',automaticLayout:true,scrollBeyondLastLine:false,wordWrap:'on'}}/></div>
        </section>
        <section className="simple-card simple-settings"><div className="simple-cardhead"><strong>Property check</strong></div><div className="simple-fields"><label>State property<input value={property} onChange={e=>setProperty(e.target.value)} placeholder="count >= 0"/></label><button type="button" className="simple-expand" onClick={()=>setAdvanced(v=>!v)}>{advanced?'Hide options':'Advanced options'} <span>{advanced?'⌃':'⌄'}</span></button>{advanced&&<div className="simple-advanced"><label>Maximum depth<input type="number" min="0" max="40" value={depth} onChange={e=>setDepth(e.target.value)}/></label><label>Maximum states<input type="number" min="1" max="500" value={limit} onChange={e=>setLimit(e.target.value)}/></label></div>}<button className="simple-primary" disabled={busy} onClick={()=>execute('verify')}>{busy?'Working…':'Run verification'}</button><button className="simple-secondary" disabled={busy} onClick={()=>execute('convert')}>Convert to Python</button><p className="simple-help">Checks a restricted TLA+ subset, not full TLC model checking.</p></div></section>
      </div>
      {error&&<div role="alert" className="simple-error">{error}</div>}
      <section className="simple-card simple-results">
        <div className="simple-cardhead"><strong>Results</strong><div className="simple-tools"><button className={tab==='graph'?'simple-active':''} onClick={()=>setTab('graph')}>State graph</button><button className={tab==='python'?'simple-active':''} onClick={()=>setTab('python')}>Python</button></div></div>
        {tab==='python'?<><div className="simple-export"><button disabled={!python} onClick={()=>save(python,'converted_model.py')}>Download Python ↓</button></div><pre className="simple-output">{python||'Select “Convert to Python” to generate code.'}</pre></>:result?<><div className="simple-metrics"><div><span>States</span><strong>{result.summary.states}</strong></div><div><span>Transitions</span><strong>{result.summary.transitions}</strong></div><div><span>Deadlocks</span><strong>{result.summary.deadlocks}</strong></div><div><span>Property</span><strong className={status==='violation'?'simple-fail':'simple-pass'}>{status==='violation'?'Violation':status==='pass_finite_graph'?'Passed':status==='bounded_pass'?'Bounded':status==='not_checked'?'Not checked':status.replaceAll('_',' ')}</strong></div></div><div className="simple-graph"><StateGraph key={JSON.stringify(result.nodes)+result.summary.property} result={result} onSelect={setSelected}/></div><div className="simple-bottom"><div><strong>State details</strong><pre>{selected?JSON.stringify(selected.state,null,2):'Click a state to inspect its values.'}</pre></div><div><strong>Counterexample</strong><p>{result.counterexample.length?result.counterexample.map(n=>'S'+n).join(' → '):'No violation found in explored states.'}</p></div></div><div className="simple-export"><button onClick={()=>save(JSON.stringify({source:code,property,verification:result},null,2),'verification_results.json','application/json')}>Export results ↓</button></div></>:<div className="simple-empty">Run verification to view the state graph and results.</div>}
      </section>
      <p className="simple-disclaimer">Research prototype. Results describe the explored state graph only. Full TLA+ and TLC execution are not provided here.</p>
    </main>
  </div>;
}
