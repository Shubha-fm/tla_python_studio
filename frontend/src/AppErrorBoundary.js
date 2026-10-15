import React from 'react';

export default class AppErrorBoundary extends React.Component {
  constructor(props){super(props);this.state={error:null};}
  static getDerivedStateFromError(error){return {error};}
  componentDidCatch(error,info){console.error('TLA+ Python Studio rendering error:',error,info);}
  render(){
    if(this.state.error) {
      return <main style={{maxWidth:800,margin:'10vh auto',padding:30,fontFamily:'system-ui',color:'#183151'}}>
        <h1>Application encountered a browser error</h1>
        <p>The server may still be running, but the interface could not finish loading.</p>
        <pre style={{background:'#f1f5fa',padding:18,whiteSpace:'pre-wrap',overflowWrap:'anywhere',borderRadius:8}}>{String(this.state.error.message||this.state.error)}</pre>
        <button style={{padding:'12px 20px',cursor:'pointer'}} onClick={()=>window.location.reload()}>Reload application</button>
        <p style={{fontSize:13,color:'#64748b'}}>Please share the error message when reporting this issue.</p>
      </main>;
    }
    return this.props.children;
  }
}
