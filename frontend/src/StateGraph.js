import React, {useMemo, useCallback} from 'react';
import {ReactFlow, Background, Controls, MiniMap, Handle, Position, MarkerType, useNodesState, useEdgesState, getBezierPath, EdgeLabelRenderer} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './StateGraph.css';

function StateNode({data, selected}) {
  return <div className={'state-node'+(data.inTrace?' trace':'')+(selected?' selected':'')} title={JSON.stringify(data.state)}>
    <Handle type="target" position={Position.Left} id="left" />
    <Handle type="target" position={Position.Top} id="top" />
    <div className="state-name">S{data.id}</div>
    <div className="state-values">{Object.entries(data.state).slice(0,3).map(([key,val])=><div key={key}>{key}: {String(val)}</div>)}</div>
    <Handle type="source" position={Position.Right} id="right"/>
    <Handle type="source" position={Position.Bottom} id="bottom"/>
  </div>;
}
const nodeTypes={state:StateNode};
function ActionEdge(props) {
 const {id,sourceX,sourceY,targetX,targetY,sourcePosition,targetPosition,data,markerEnd,style}=props;
 const [path,labelX,labelY]=getBezierPath({sourceX,sourceY,targetX,targetY,sourcePosition,targetPosition,curvature:data?.curvature||0.32});
 return <><path id={id} className="react-flow__edge-path" d={path} markerEnd={markerEnd} style={style}/><EdgeLabelRenderer><div className={'action-label'+(data?.inTrace?' trace':'')} style={{position:'absolute',transform:'translate(-50%,-50%) translate('+ (labelX+(data?.offset||0))+'px,'+(labelY+(data?.verticalOffset||0))+'px)',pointerEvents:'none'}}>{data?.action||'Next'}</div></EdgeLabelRenderer></>;
}
const edgeTypes={action:ActionEdge};

function layout(graph) {
 const nodes=graph.nodes||[],edges=graph.edges||[];
 const depthGroups=new Map();
 nodes.forEach(n=>{const d=n.depth||0;if(!depthGroups.has(d))depthGroups.set(d,[]);depthGroups.get(d).push(n)});
 const trace=new Set(graph.counterexample||[]);
 const layoutNodes=nodes.map(n=>{
   const group=depthGroups.get(n.depth||0);
   const index=group.findIndex(x=>x.id===n.id);
   return {id:String(n.id),type:'state',position:{x:60+(n.depth||0)*245,y:70+index*165-(group.length-1)*42},data:{id:n.id,state:n.state,inTrace:trace.has(n.id)},draggable:true};
 });
 const pairs=new Map();
 edges.forEach(e=>{const k=e.source+':'+e.target;pairs.set(k,(pairs.get(k)||0)+1)});
 const counts=new Map();
 const layoutEdges=edges.map((e,i)=>{
   const k=e.source+':'+e.target;const index=counts.get(k)||0;counts.set(k,index+1);
   const inTrace=(graph.counterexample||[]).some((id,j,a)=>j<a.length-1&&id===e.source&&a[j+1]===e.target);
   const reverse=edges.some(x=>x.source===e.target&&x.target===e.source);
   const loop=e.source===e.target;
   const backward=!loop&&Number(e.target)<Number(e.source);
   return {id:'transition-'+i,source:String(e.source),target:String(e.target),sourceHandle:loop||backward?'bottom':'right',targetHandle:loop||backward?'top':'left',type:'action',label:undefined,markerEnd:{type:MarkerType.ArrowClosed,color:inTrace?'#dd4863':'#6684ae',width:19,height:19},style:{stroke:inTrace?'#dd4863':'#6684ae',strokeWidth:inTrace?3:1.8},data:{action:e.action||'Next',inTrace,offset:(index-(pairs.get(k)-1)/2)*46+(reverse?15:0),verticalOffset:loop?-26:backward?30:0,curvature:0.3+index*0.16}};
 });
 return {layoutNodes,layoutEdges};
}
export default function StateGraph({result,onSelect}) {
 const initial=useMemo(()=>layout(result),[result]);
 const [nodes,setNodes,onNodesChange]=useNodesState(initial.layoutNodes);
 const [edges,,onEdgesChange]=useEdgesState(initial.layoutEdges);
 const handleClick=useCallback((event,node)=>{const state=(result.nodes||[]).find(n=>String(n.id)===node.id);onSelect(state||null)},[result,onSelect]);
 return <div className="flow-container" role="region" aria-label="Interactive state transition graph">
  <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onNodeClick={handleClick} nodesDraggable nodesConnectable={false} elementsSelectable fitView fitViewOptions={{padding:0.25,maxZoom:1.2}} minZoom={0.2} maxZoom={2.5} proOptions={{hideAttribution:false}}>
   <Background color="#dce6f3" gap={20} size={1}/><MiniMap pannable zoomable nodeColor={n=>n.data.inTrace?'#dd4863':'#275382'} /><Controls showInteractive={false}/>
  </ReactFlow>
 </div>;
}
