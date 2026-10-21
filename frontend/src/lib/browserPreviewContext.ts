import type {PendingAction} from '../types';
import type {BrowserSession} from '../api/platform';
export type PreviewSelection={actionId:string;index:number}|null;
export function browserPreviewContext(conversationId:string,sessions:BrowserSession[],actions:PendingAction[],selection:PreviewSelection,chosen:string){
 const candidates=actions.filter(a=>a.action==='browser_actions'&&a.conversation_id===conversationId&&(a.status==='pending'||a.status==='executing'));
 const selected=actions.find(a=>a.id===selection?.actionId&&a.action==='browser_actions'&&a.conversation_id===conversationId);
 const source=selected||candidates[candidates.length-1];
 const action=source&&['pending','executing'].includes(source.status)?source:undefined;
 const session=source?sessions.find(s=>s.id===source.params.session_id):sessions.find(s=>s.id===chosen)||sessions[sessions.length-1];
 const requested=action&&selection?.actionId===action.id?selection.index:0;
 const index=action&&requested>=0&&requested<(action.params.operations?.length||0)?requested:0;
 return {action,source,session,index};
}
