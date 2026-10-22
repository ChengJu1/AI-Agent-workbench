import type {BrowserFrame} from '../api/platform';

export async function previewRequest<T>(read:(signal:AbortSignal)=>Promise<T>,signal?:AbortSignal,timeoutMs=8000):Promise<T>{
 const controller=new AbortController();
 let timer:ReturnType<typeof setTimeout>;
 let abort:()=>void=()=>{};
 try{return await new Promise<T>((resolve,reject)=>{
  abort=()=>{controller.abort();reject(new DOMException('Preview cancelled','AbortError'));};
  if(signal?.aborted){abort();return;}
  signal?.addEventListener('abort',abort,{once:true});
  timer=setTimeout(()=>{controller.abort();reject(new Error('预览连接超时。你可以重试画面或重新打开网页，聊天仍可继续。'));},timeoutMs);
  Promise.resolve().then(()=>read(controller.signal)).then(resolve,reject);
 });}finally{clearTimeout(timer!);signal?.removeEventListener('abort',abort);}
}

export function browserFrame(value:unknown):BrowserFrame{
 const data=value as Partial<BrowserFrame>|null;
 if(!data||typeof data.image!=='string'||!data.image.startsWith('data:image/png;base64,')||typeof data.url!=='string'||
  !Number.isFinite(data.captured_at)||!data.viewport||!Number.isFinite(data.viewport.width)||data.viewport.width<=0||!Number.isFinite(data.viewport.height)||data.viewport.height<=0){
  throw new Error('预览数据不完整，请重试画面。');
 }
 const progress=data.progress&&typeof data.progress==='object'?data.progress:{};
 const target=data.target;
 if(target&&(typeof target.label!=='string'||typeof target.kind!=='string'||(target.box&&
  ![target.box.x,target.box.y,target.box.width,target.box.height].every(Number.isFinite))))throw new Error('预览控件数据不完整，请重试画面。');
 return {...data,progress,target:target||null,manual_until:data.manual_until||0} as BrowserFrame;
}
