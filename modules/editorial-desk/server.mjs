import { randomUUID } from 'node:crypto';

const json = (data, status=200) => new Response(JSON.stringify(data), {status, headers:{'content-type':'application/json; charset=utf-8'}});
const fields = { title:300, body:100000, sourceUrl:2048, organization:300, deadline:100, region:300 };
function validate(input, creation=false) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return '객체 형식으로 입력하세요.';
  if (creation && (typeof input.title !== 'string' || !input.title.trim())) return '제목이 필요합니다.';
  for (const [key,max] of Object.entries(fields)) if (key in input && (typeof input[key] !== 'string' || input[key].length>max || (key==='title' && !input[key].trim()))) return `${key} 입력을 확인하세요 (최대 ${max}자).`;
  if ('questions' in input && (!Array.isArray(input.questions) || input.questions.length>50 || input.questions.some(q=>typeof q!=='string' || q.length>2000))) return '질문은 최대 50개, 각 2000자 문자열이어야 합니다.';
  if ('origin' in input && !['manual','opportunity'].includes(input.origin)) return 'origin 입력을 확인하세요.';
  return null;
}
function select(input) { const result={}; for(const key of [...Object.keys(fields),'questions','origin']) if(key in input) result[key]=input[key]; return result; }
function https(value) { try {const u=new URL(value);return u.protocol==='https:' && !!u.hostname && !u.username && !u.password;} catch{return false;} }

export async function handleDesk(request, context) {
  const pathname=new URL(request.url).pathname;
  const match=pathname.match(/^\/api\/desk\/articles(?:\/([^/]+)(\/transition)?)?$/);
  if (!match) return null;
  const [,id,transition]=match;
  if(request.method==='GET' && !id) return json({ok:true,items:context.read().articles || []});
  if ((!id && request.method!=='POST') || (id && !transition && request.method!=='PATCH') || (transition && request.method!=='POST')) return json({ok:false,error:'지원하지 않는 요청입니다.'},405);
  let input; try {input=await request.json();} catch {return json({ok:false,error:'올바른 JSON이 필요합니다.'},400);}
  if (!input || typeof input!=='object' || Array.isArray(input)) return json({ok:false,error:'객체 형식으로 입력하세요.'},400);
  if (!transition) {const error=validate(input,!id);if(error)return json({ok:false,error},400);}
  const now=new Date().toISOString();
  const result=context.update(state=>{
    state.articles ||= [];
    if(!id){const item={title:input.title.trim(),body:'',sourceUrl:'',organization:'',deadline:'',region:'',questions:[],origin:'manual',...select(input),id:randomUUID(),status:'draft',createdAt:now,updatedAt:now};state.articles.push(item);return {item};}
    const item=state.articles.find(item=>item.id===id);
    if(!item)return {error:'기사를 찾을 수 없습니다.',status:404};
    if(transition){
      const next=input.status;
      if(!['draft','review','published'].includes(next))return {error:'상태 입력을 확인하세요.',status:400};
      const allowed={draft:['review'],review:['draft','published'],published:['draft']};
      if(!allowed[item.status]?.includes(next))return {error:'허용되지 않는 상태 전환입니다.',status:409};
      if(['review','published'].includes(next) && !item.body.trim())return {error:'검토와 발행에는 기사 본문이 필요합니다.',status:409};
      if(next==='published' && (!item.title.trim() || !https(item.sourceUrl)))return {error:'발행에는 제목과 유효한 HTTPS 출처 링크가 필요합니다.',status:409};
      item.status=next;
      if(next==='review')item.reviewedAt=now;
      if(next==='published')item.publishedAt=now;
      if(next==='draft') {delete item.publishedAt;delete item.reviewedAt;}
    } else {
      if(item.status==='published' && ('body' in input || 'title' in input))return {error:'발행 기사의 제목·본문을 수정하려면 초안으로 되돌리세요.',status:409};
      Object.assign(item,select(input));
    }
    item.updatedAt=now;
    return {item};
  });
  return result.error?json({ok:false,error:result.error},result.status):json({ok:true,item:result.item},!id?201:200);
}
