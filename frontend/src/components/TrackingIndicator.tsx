import {useEffect,useState} from 'react';
import {fetchTracking} from '../api/tracking';
export function TrackingIndicator({disabled,onOpen}:{disabled:boolean;onOpen:()=>void}){
 const [count,setCount]=useState(0);
 useEffect(()=>{const c=new AbortController();let timer:ReturnType<typeof setTimeout>;async function poll(){try{const tasks=await fetchTracking(c.signal);if(!c.signal.aborted)setCount(tasks.reduce((sum,t)=>sum+t.unread,0));}catch{}finally{if(!c.signal.aborted)timer=setTimeout(()=>void poll(),15000);}}void poll();return()=>{c.abort();clearTimeout(timer);};},[]);
 return <button disabled={disabled} onClick={onOpen}>记录与跟踪{count?` · ${count} 条新消息`:''}</button>;
}
