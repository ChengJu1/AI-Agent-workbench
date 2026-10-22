// Reload only after explicit resource approval; preserve the existing handoff deadline.
export async function restoreBrowserResources<T>({manualUntil,isCurrent,handoff,reload,resume,now=()=>Date.now()/1000}:{
 manualUntil:number;isCurrent:()=>boolean;handoff:()=>Promise<unknown>;reload:()=>Promise<T>;resume:(seconds:number)=>Promise<unknown>;now?:()=>number;
}):Promise<T|undefined>{
 if(!isCurrent())return;
 const wasManual=manualUntil>now();
 if(wasManual)await handoff();
 if(!isCurrent())return;
 const page=await reload();
 if(!isCurrent())return;
 const remaining=Math.floor(manualUntil-now());
 if(wasManual&&remaining>=30)await resume(Math.min(remaining,600));
 return page;
}
