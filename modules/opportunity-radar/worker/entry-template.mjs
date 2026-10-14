const page = __PAGE_JSON__;
const JSON_HEADERS = { "content-type": "application/json; charset=utf-8", "cache-control": "public, s-maxage=300, stale-while-revalidate=600" };
const EVENT_TERMS = ["행사", "축제", "운영", "홍보", "광고", "콘텐츠", "영상", "제작", "문화", "캠페인", "전시", "공연", "포럼", "컨퍼런스", "박람회", "마라톤", "스포츠", "미디어"];
const NOTICE_TERMS = /(지원|공모|모집|행사|입찰|용역|콘텐츠|마케팅|홍보|영상|축제|협력|선정|문화|미디어)/;
const response = (data, status=200) => new Response(JSON.stringify(data), { status, headers: JSON_HEADERS });
const privateResponse = (data, status=200) => new Response(JSON.stringify(data), { status, headers: {"content-type":"application/json; charset=utf-8","cache-control":"no-store"} });
const xmlText = (s="") => s.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g,"$1").replace(/<[^>]*>/g," ").replace(/&amp;/g,"&").replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/\s+/g," ").trim();
const tag = (block, name) => xmlText(block.match(new RegExp(`<${name}[^>]*>([\\s\\S]*?)<\\/${name}>`,"i"))?.[1] || "");
function dateOnly(value) {
  const raw=String(value||"").replace(/\D/g,"");
  return raw.length>=8 ? `${raw.slice(0,4)}-${raw.slice(4,6)}-${raw.slice(6,8)}` : null;
}
function currentKstWindow() {
  const kstNow = new Date(Date.now()+9*60*60*1000);
  const end = kstNow.toISOString().slice(0,10).replaceAll("-","");
  const start = new Date(kstNow.getTime()-14*24*60*60*1000).toISOString().slice(0,10).replaceAll("-","");
  return { begin:`${start}0000`, end:`${end}2359` };
}
function toG2BItem(x) {
  const title=String(x.bidNtceNm||x.bidNtceNmEng||"").replace(/<[^>]*>/g,"").trim();
  if (!title || !EVENT_TERMS.some(term=>title.includes(term))) return null;
  const close=dateOnly(x.bidClseDt||x.bidClseDtFmt);
  const now=new Date(new Date().toLocaleString("en-US",{timeZone:"Asia/Seoul"}));
  if (close && new Date(close+"T23:59:59")<now) return null;
  const id=`g2b-${x.bidNtceNo||title}-${x.bidNtceOrd||"0"}`;
  const date=dateOnly(x.ntceDt||x.bidNtceDt||x.bidNtceRegDt) || new Date().toISOString().slice(0,10);
  const amount=Number(x.asignBdgtAmt||x.presmptPrce||0);
  const budget=amount ? `${new Intl.NumberFormat("ko-KR").format(amount)}원` : "공고 원문 확인";
  const org=x.ntceInsttNm||x.dminsttNm||"나라장터 공고기관";
  const detail=x.bidNtceDtlUrl||"https://www.g2b.go.kr/";
  const field=/축제|행사|공연|전시|마라톤|스포츠/.test(title)?"행사·축제":"콘텐츠·미디어";
  return {id,title,org,source:"나라장터",field,kind:"용역입찰",deadline:close,start:date,budget,match:/행사|축제|공연|전시|콘텐츠|미디어/.test(title)?91:78,open:true,link:detail,description:`나라장터 입찰공고 API에서 수집한 용역 공고입니다. 공고기관: ${org}. 참가자격과 과업 범위는 원문과 제안요청서에서 확인하세요.`,requirements:"입찰참가자격, 유사 실적, 공동수급 허용 여부, 제출 서류와 평가 기준을 원문에서 확인",idea:"콘텐츠 기획·영상·행사 운영·온라인 홍보를 결합할 수 있는지 제안요청서의 과업 범위부터 대조합니다.",demo:false,live:true};
}
async function getG2B(env) {
  if (!env.G2B_SERVICE_KEY) return response({ok:false,source:"나라장터",error:"API 서비스 키가 설정되지 않았습니다.",items:[]},503);
  const {begin,end}=currentKstWindow();
  const u=new URL("https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc");
  for (const [k,v] of Object.entries({ServiceKey:env.G2B_SERVICE_KEY,type:"json",inqryDiv:"1",inqryBgnDt:begin,inqryEndDt:end,pageNo:"1",numOfRows:"100"})) u.searchParams.set(k,v);
  let upstream;
  try { upstream=await fetch(u.toString(),{headers:{accept:"application/json"},cf:{cacheTtl:300,cacheEverything:true}}); }
  catch { return response({ok:false,source:"나라장터",error:"조달청 API에 연결하지 못했습니다.",items:[]},502); }
  if (!upstream.ok) return response({ok:false,source:"나라장터",error:`조달청 API 응답 오류 (${upstream.status}).`,items:[]},502);
  let payload;
  try { payload=await upstream.json(); } catch { return response({ok:false,source:"나라장터",error:"API 응답 형식을 확인할 수 없습니다.",items:[]},502); }
  const head=payload?.response?.header;
  const body=payload?.response?.body;
  if (head && !["00","0"].includes(String(head.resultCode))) return response({ok:false,source:"나라장터",error:`조달청 API 코드 ${head.resultCode||"확인 불가"}: ${head.resultMsg||"요청 실패"}`,items:[]},502);
  let rows=body?.items?.item||[];
  if (!Array.isArray(rows)) rows=rows?[rows]:[];
  const items=rows.map(toG2BItem).filter(Boolean).slice(0,60);
  return response({ok:true,source:"나라장터",updatedAt:new Date().toISOString(),count:items.length,items});
}

function recentTradeMonths() {
  const now = new Date(Date.now()+9*60*60*1000);
  const current = new Date(Date.UTC(now.getUTCFullYear(),now.getUTCMonth(),1));
  const end = new Date(current.getTime()-86400000);
  const start = new Date(Date.UTC(end.getUTCFullYear(),end.getUTCMonth()-2,1));
  const ym = d => `${d.getUTCFullYear()}${String(d.getUTCMonth()+1).padStart(2,"0")}`;
  return {start:ym(start),end:ym(end)};
}
async function getCustomsTrade(env, requestUrl) {
  if (!env.CUSTOMS_SERVICE_KEY) return response({ok:false,source:"관세청",error:"관세청 API 키가 서버에 설정되지 않았습니다.",items:[]},503);
  const country=(requestUrl.searchParams.get("country")||"US").toUpperCase();
  const hs=requestUrl.searchParams.get("hs")||"";
  if (!/^[A-Z]{2}$/.test(country) || (hs && !/^\d{2,10}$/.test(hs))) return response({ok:false,source:"관세청",error:"국가코드 또는 HS 품목코드 형식을 확인해 주세요.",items:[]},400);
  const {start,end}=recentTradeMonths();
  const u=new URL("https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList");
  for (const [k,v] of Object.entries({serviceKey:env.CUSTOMS_SERVICE_KEY,strtYymm:start,endYymm:end,cntyCd:country})) u.searchParams.set(k,v);
  if (hs) u.searchParams.set("hsSgn",hs);
  let upstream;
  try { upstream=await fetch(u.toString(),{headers:{accept:"application/xml, text/xml"},cf:{cacheTtl:3600,cacheEverything:true}}); }
  catch { return response({ok:false,source:"관세청",error:"관세청 API에 연결하지 못했습니다.",items:[]},502); }
  if (!upstream.ok) return response({ok:false,source:"관세청",error:`관세청 API 응답 오류 (${upstream.status}).`,items:[]},502);
  const text=await upstream.text();
  const code=tag(text,"resultCode"), message=tag(text,"resultMsg");
  if (code && code!=="00" && code!=="0") return response({ok:false,source:"관세청",error:`관세청 API 코드 ${code}: ${message||"요청 실패"}`,items:[]},502);
  const rows=[...text.matchAll(/<item\b[^>]*>([\s\S]*?)<\/item>/gi)].map(m=>m[1]).map(row=>({
    month:tag(row,"year"),country:tag(row,"statCdCntnKor1"),countryCode:tag(row,"statCd"),product:tag(row,"statKor"),hsCode:tag(row,"hsCd"),
    exportWeight:tag(row,"expWgt"),exportUsd:tag(row,"expDlr"),importWeight:tag(row,"impWgt"),importUsd:tag(row,"impDlr"),balanceUsd:tag(row,"balPayments")
  }));
  return response({ok:true,source:"관세청 품목별 국가별 수출입실적",updatedAt:new Date().toISOString(),country,count:rows.length,statistics:rows,items:[]});
}

function bizinfoRows(payload) {
  const root=payload?.jsonArray||payload?.response||payload;
  let rows=root?.item||root?.items||[];
  if (!Array.isArray(rows)) rows=rows?[rows]:[];
  return rows;
}
function periodEnd(value) {
  const text=String(value||"");
  const matches=[...text.matchAll(/(20\d{2})[-./ ]?(\d{2})[-./ ]?(\d{2})/g)];
  return matches.length?`${matches.at(-1)[1]}-${matches.at(-1)[2]}-${matches.at(-1)[3]}`:null;
}
function cleanHtml(value="") { return String(value).replace(/<[^>]*>/g," ").replace(/&nbsp;/g," ").replace(/&amp;/g,"&").replace(/\s+/g," ").trim(); }
function mapBizinfoSupport(row,i) {
  const title=row.title||row.pblancNm||"";
  if (!title) return null;
  const period=row.reqstMthPapersCn||row.reqstBeginEndDe||row.reqstDt||"";
  const deadline=periodEnd(period);
  const id=row.seq||row.pblancId||`support-${i}`;
  return {id:`bizinfo-${id}`,title,org:row.author||row.jrsdInsttNm||row.excInsttNm||"기업마당 공고기관",source:"기업마당",field:row.lcategory||row.pldirSportRealmLclasCodeNm||"창업·경영",kind:"지원사업",deadline,start:dateOnly(row.pubDate||row.creatPnttm)||new Date().toISOString().slice(0,10),budget:"공고 원문 확인",match:84,open:!deadline||new Date(deadline+"T23:59:59.999+09:00")>=new Date(),link:row.pblancUrl||row.link||row.pblancUrl||"https://www.bizinfo.go.kr/",description:cleanHtml(row.bsnsSumryCn||row.description||"기업마당 지원사업 API에서 수집했습니다."),requirements:`지원 대상: ${row.trgetNm||"원문 확인"}. 신청기간과 제출서류는 원문에서 확인하세요.`,idea:"사업 목적과 당사 콘텐츠·행사 역량을 대조한 뒤 제작·홍보·지역 행사 제안으로 연결합니다.",demo:false,live:true};
}
function mapBizinfoEvent(row,i) {
  const title=row.title||row.nttNm||"";
  if (!title) return null;
  const deadline=periodEnd(row.rceptPd||row.receptionPeriod||"");
  const id=row.seq||row.eventInfoId||`event-${i}`;
  return {id:`bizinfo-event-${id}`,title,org:row.originOrg||row.originEngnNm||"행사 주관기관 원문 확인",source:"기업마당",field:row.lcategory||row.eventType||row.eventInfoTyNm||"행사·축제",kind:row.eventType||row.eventInfoTyNm||"행사정보",deadline,start:dateOnly(row.registDe||row.pubDate)||new Date().toISOString().slice(0,10),budget:"참가 조건 원문 확인",match:79,open:!deadline||new Date(deadline+"T23:59:59.999+09:00")>=new Date(),link:row.originUrl||row.originUrlAdres||row.bizinfoUrl||row.link||"https://www.bizinfo.go.kr/",description:cleanHtml(row.description||row.nttCn||"기업마당 행사정보 API에서 수집했습니다."),requirements:"참가 대상, 접수기간, 행사 일정과 비용을 원문에서 확인하세요.",idea:"포럼·세미나·전시 정보를 파트너 발굴과 콘텐츠 취재 기회로 검토합니다.",demo:false,live:true};
}
async function getBizinfo(env, kind) {
  const serviceKey=kind==="event"?env.BIZINFO_EVENT_KEY:env.BIZINFO_SUPPORT_KEY;
  if (!serviceKey) return response({ok:false,source:kind,error:"기업마당 서비스 키가 필요합니다.",items:[]},503);
  const isEvent=kind==="event";
  const endpoint=isEvent?"https://www.bizinfo.go.kr/uss/rss/bizinfoEventApi.do":"https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do";
  const u=new URL(endpoint);
  u.searchParams.set("crtfcKey",serviceKey);
  u.searchParams.set("dataType","json");
  u.searchParams.set("searchCnt","100");
  u.searchParams.set("pageUnit","100");
  u.searchParams.set("pageIndex","1");
  let upstream;
  try { upstream=await fetch(u.toString(),{headers:{accept:"application/json"},cf:{cacheTtl:300,cacheEverything:true}}); }
  catch { return response({ok:false,source:kind,error:"기업마당 API에 연결하지 못했습니다.",items:[]},502); }
  if (!upstream.ok) return response({ok:false,source:kind,error:`기업마당 API 응답 오류 (${upstream.status}).`,items:[]},502);
  let payload;
  try { payload=await upstream.json(); } catch { return response({ok:false,source:kind,error:"기업마당 API 응답 형식을 확인할 수 없습니다.",items:[]},502); }
  const mapper=isEvent?mapBizinfoEvent:mapBizinfoSupport;
  const items=bizinfoRows(payload).map(mapper).filter(Boolean).filter(item=>item.open).slice(0,80);
  return response({ok:true,source:kind,updatedAt:new Date().toISOString(),count:items.length,items});
}
async function getCultureRss(feed="notice") {
  const endpoint=feed==="press"?"https://www.mcst.go.kr/common/rss/press.jsp":"https://www.mcst.go.kr/common/rss/notice.jsp";
  const source=feed==="press"?"문화체육관광부 보도자료 RSS":"문화체육관광부 공지 RSS";
  let upstream;
  try { upstream=await fetch(endpoint,{headers:{accept:"application/rss+xml, application/xml, text/xml"},cf:{cacheTtl:600,cacheEverything:true}}); }
  catch { return response({ok:false,source,error:"문체부 RSS에 연결하지 못했습니다.",items:[]},502); }
  if (!upstream.ok) return response({ok:false,source,error:`문체부 RSS 응답 오류 (${upstream.status}).`,items:[]},502);
  const text=await upstream.text();
  const items=[...text.matchAll(/<item\b[^>]*>([\s\S]*?)<\/item>/gi)].map((m,i)=>{
    const b=m[1], title=tag(b,"title"), link=tag(b,"link"), description=tag(b,"description"), pubDate=tag(b,"pubDate");
    if (!title || (feed!=="press"&&!NOTICE_TERMS.test(title))) return null;
    const date=pubDate ? new Date(pubDate) : null;
    return {id:`mcst-${feed}-${link||i}`,title,org:"문화체육관광부",source:feed==="press"?"문화체육관광부 보도자료":"문화·지역기관",field:/행사|축제|공연|전시|관광/.test(title)?"행사·축제":"콘텐츠·미디어",kind:feed==="press"?"정책 보도자료":"공고·정책 알림",deadline:null,start:date&&!Number.isNaN(date.valueOf())?date.toISOString().slice(0,10):new Date().toISOString().slice(0,10),budget:"원문 확인",match:76,open:true,link:link||"https://www.mcst.go.kr/",description:description||"문체부 RSS에서 수집한 게시물입니다. 지원 자격과 모집 기간은 원문에서 확인하세요.",requirements:"RSS에는 마감일과 세부 자격이 포함되지 않을 수 있습니다. 공고 원문과 첨부파일을 확인하세요.",idea:"문화·관광·콘텐츠 정책 또는 행사와 사업 기회를 원문에서 확인합니다.",demo:false,live:true};
  }).filter(Boolean).slice(0,30);
  return response({ok:true,source:"문화체육관광부 RSS",updatedAt:new Date().toISOString(),count:items.length,items});
}

function safeCustomEndpoint(raw) {
  let u;
  try { u=new URL(raw); } catch { return null; }
  const host=u.hostname.toLowerCase();
  if (u.protocol!=="https:" || u.username || u.password || (u.port && u.port!=="443")) return null;
  if (!(host==="go.kr" || host.endsWith(".go.kr"))) return null;
  if (host==="localhost" || host.endsWith(".localhost") || /^\d+(\.\d+){3}$/.test(host) || host.includes(":")) return null;
  for (const key of [...u.searchParams.keys()]) if (/^(servicekey|crtfcKey|api[_-]?key|access[_-]?token|token)$/i.test(key)) return null;
  return u;
}
function xmlBlockValue(block,names) {
  for (const name of names) {
    const match=block.match(new RegExp(`<${name}(?:\\s[^>]*)?>([\\s\\S]*?)<\\/${name}>`,`i`));
    if (match) return xmlText(match[1]);
  }
  return "";
}
function recordsAt(payload,path="") {
  let value=payload;
  if (path.trim()) for (const part of path.trim().split(".")) value=value?.[part];
  else value=payload?.items??payload?.data?.items??payload?.data?.item??payload?.data??payload?.response?.body?.items?.item??payload?.response?.body?.items??payload?.response?.body?.item??payload?.jsonArray??payload?.results??payload?.item??payload;
  if (value?.item!==undefined && !Array.isArray(value)) value=value.item;
  if (!Array.isArray(value)) value=value&&typeof value==="object"?[value]:[];
  return value;
}
function mapCustomRecord(row,index,name) {
  const pick=(...keys)=>{for(const key of keys){const value=row?.[key];if(value!==undefined&&value!==null&&String(value).trim())return String(value).trim()}return ""};
  const title=pick("title","pblancNm","pblancName","bidNtceNm","nttSj","subject","name","bizNm","eventNm");
  if (!title) return null;
  const link=pick("link","url","pblancUrl","bidNtceDtlUrl","detailUrl","originUrl","homepageUrl");
  const rawDate=pick("pubDate","start","startDate","registDe","creatPnttm","createdAt","ntceDt","bidNtceDt");
  const parsedDate=rawDate?new Date(rawDate):null;
  const date=parsedDate&&!Number.isNaN(parsedDate.valueOf())?parsedDate.toISOString().slice(0,10):new Date().toISOString().slice(0,10);
  const period=pick("deadline","endDate","reqstDt","reqstBeginEndDe","rceptEndDt","bidClseDt","closeDate","applyEnd");
  const endMatch=period.match(/(20\d{2})[-./ ]?(\d{2})[-./ ]?(\d{2})/g)?.at(-1);
  const deadline=endMatch?dateOnly(endMatch):null;
  return {id:`custom-${name}-${pick("id","seq","pblancId","eventInfoId")||index}`,title,org:pick("org","author","jrsdInsttNm","excInsttNm","agency","organNm")||name,source:name,field:pick("field","category","lcategory","supportField")||"공공사업",kind:pick("kind","type","eventType","businessType")||"지원·공모",deadline,start:date,budget:pick("budget","amount","supportBudget")||"공고 원문 확인",match:70,open:!deadline||new Date(deadline+"T23:59:59.999+09:00")>=new Date(),link:link.startsWith("https://")?link:"https://www.go.kr/",description:cleanHtml(pick("description","bsnsSumryCn","summary","content","contents","overview")),requirements:cleanHtml(pick("requirements","target","trgetNm","eligibility"))||"지원 자격·신청기간·제출 서류는 원문에서 확인하세요.",idea:"공고의 지원대상과 사업 목적을 검토한 뒤 당사 사업과 연결할 수 있는지 확인합니다.",demo:false,live:true};
}
function mapCustomXmlRecord(block,index,name) {
  const row={title:xmlBlockValue(block,["title","pblancNm","bidNtceNm","nttSj"]),link:xmlBlockValue(block,["link","url","pblancUrl","bidNtceDtlUrl"]),description:xmlBlockValue(block,["description","summary","bsnsSumryCn","content"]),pubDate:xmlBlockValue(block,["pubDate","registDe","createdAt","ntceDt"]),deadline:xmlBlockValue(block,["deadline","endDate","reqstDt","rceptEndDt"]),author:xmlBlockValue(block,["author","org","agency"]),category:xmlBlockValue(block,["category","lcategory"]),id:xmlBlockValue(block,["id","seq","pblancId"])};
  return mapCustomRecord(row,index,name);
}
async function collectCustomSource(request) {
  try {
    const raw=await request.text();
    if (raw.length>12000) return privateResponse({ok:false,error:"요청 크기가 너무 큽니다."},413);
    const input=JSON.parse(raw||"{}");
    const name=String(input.name||"").trim().slice(0,80),kind=input.kind==="rss"||input.kind==="xml"?input.kind:"json";
    const endpoint=safeCustomEndpoint(String(input.url||""));
    if (!name || !endpoint) return privateResponse({ok:false,error:"공공기관 HTTPS API/RSS 주소만 연결할 수 있습니다."},400);
    const authMode=input.authMode==="query"||input.authMode==="header"?input.authMode:"none";
    const authName=String(input.authName|| (authMode==="query"?"crtfcKey":"Authorization")).trim().slice(0,100);
    const apiKey=String(input.apiKey||"").trim().slice(0,2000);
    if (authMode!=="none" && (!authName || !apiKey)) return privateResponse({ok:false,error:"인증 방식과 키 값을 확인해 주세요."},400);
    if (authMode==="query" && !/^[A-Za-z0-9_.~-]{1,100}$/.test(authName)) return privateResponse({ok:false,error:"인증 파라미터 이름을 확인해 주세요."},400);
    if (authMode==="header" && (!/^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,100}$/.test(authName) || /^(host|cookie|set-cookie|content-length|connection|transfer-encoding)$/i.test(authName))) return privateResponse({ok:false,error:"인증 헤더 이름을 확인해 주세요."},400);
    const target=new URL(endpoint);
    const headers=new Headers({accept:kind==="json"?"application/json, application/*+json":"application/rss+xml, application/atom+xml, application/xml, text/xml"});
    if (authMode==="query") target.searchParams.set(authName,apiKey);
    if (authMode==="header") headers.set(authName,apiKey);
    let upstream;
    try { upstream=await fetch(target.toString(),{method:"GET",headers,signal:AbortSignal.timeout(12000),cache:"no-store",redirect:"manual"}); }
    catch { return privateResponse({ok:false,error:"출처 API에 연결하지 못했습니다."},502); }
    if (upstream.status>=300 && upstream.status<400) return privateResponse({ok:false,error:"출처 주소가 다른 주소로 이동해 수집을 중단했습니다. 최종 HTTPS API 주소를 입력해 주세요."},502);
    if (!upstream.ok) return privateResponse({ok:false,error:`출처 API 응답 오류 (${upstream.status}).`},502);
    const body=await upstream.text();
    if (body.length>2_000_000) return privateResponse({ok:false,error:"응답이 너무 커서 수집을 중단했습니다."},502);
    let items=[];
    if (kind==="json") {
      let payload;
      try { payload=JSON.parse(body); } catch { return privateResponse({ok:false,error:"JSON 응답을 확인하지 못했습니다. API 형식을 확인해 주세요."},502); }
      items=recordsAt(payload,String(input.itemsPath||"")).map((row,i)=>mapCustomRecord(row,i,name)).filter(Boolean);
    } else {
      const blocks=[...body.matchAll(/<(?:item|entry)\b[^>]*>([\s\S]*?)<\/(?:item|entry)>/gi)].map(match=>match[1]);
      items=blocks.map((block,i)=>mapCustomXmlRecord(block,i,name)).filter(Boolean);
    }
    return privateResponse({ok:true,source:name,updatedAt:new Date().toISOString(),count:items.length,items:items.slice(0,100)});
  } catch {
    return privateResponse({ok:false,error:"출처 설정 또는 응답 형식을 확인해 주세요."},400);
  }
}
async function getKstartup(env) {
  if (!env.DATA_GO_KR_SERVICE_KEY) return response({ok:false,error:"공공데이터 인증키가 서버에 설정되지 않았습니다.",items:[]},503);
  const endpoint=new URL("https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01");
  for(const [key,value] of Object.entries({ServiceKey:env.DATA_GO_KR_SERVICE_KEY,page:"1",perPage:"100",returnType:"json"})) endpoint.searchParams.set(key,value);
  try {
    const upstream=await fetch(endpoint,{signal:AbortSignal.timeout(10000),redirect:"error"});
    if(!upstream.ok) return response({ok:false,error:`K-Startup API 응답 오류 (${upstream.status})`,items:[]},502);
    const text=await upstream.text();
    let payload;
    try { payload=JSON.parse(text); } catch {
      const code=tag(text,"returnReasonCode")||tag(text,"resultCode");
      return response({ok:false,error:code?`K-Startup 인증·서비스 오류 (${code})`:"K-Startup JSON 응답 형식을 확인해 주세요.",items:[]},502);
    }
    const rows=recordsAt(payload);
    if(!Array.isArray(payload?.data)&&!Array.isArray(payload?.items)&&!payload?.response&&!Array.isArray(payload)) return response({ok:false,error:"K-Startup 응답 항목 또는 인증 상태를 확인해 주세요.",items:[]},502);
    const items=rows.map((row,index)=>{
      const title=cleanHtml(row.biz_pbanc_nm||"");if(!title)return null;
      let link=String(row.detl_pg_url||"").trim();if(link.startsWith("www.k-startup.go.kr/"))link="https://"+link;
      const item=mapCustomRecord({title,link,id:row.pbanc_sn||link||title,start:dateOnly(row.pbanc_rcpt_bgng_dt),deadline:dateOnly(row.pbanc_rcpt_end_dt),org:row.pbanc_ntrp_nm||row.sprv_inst,description:row.pbanc_ctnt,requirements:row.aply_trgt_ctnt||row.aply_trgt},index,"K-Startup");
      const fieldText=String(row.supt_biz_clsfc||"");
      const flag=String(row.rcrt_prgs_yn||row.Rcrt_prgs_yn||"").toUpperCase();
      return {...item,id:"kstartup-"+encodeURIComponent(String(row.pbanc_sn||link||title)),field:/행사|네트워/.test(fieldText)?"행사·축제":/기술|R&D/.test(fieldText)?"기술·R&D":"창업·경영",kind:"창업지원",open:flag==="N"?false:item.open};
    }).filter(Boolean);
    return response({ok:true,source:"K-Startup",count:items.length,items,updatedAt:new Date().toISOString()});
  } catch { return response({ok:false,error:"K-Startup API 연결 실패 또는 응답 시간 초과",items:[]},502); }
}
async function getMsit(env) {
  if (!env.DATA_GO_KR_SERVICE_KEY) return response({ok:false,error:"공공데이터 인증키가 서버에 설정되지 않았습니다.",items:[]},503);
  const endpoint=new URL("https://apis.data.go.kr/1721000/msitannouncementinfo/businessAnnouncMentList");
  for(const [key,value] of Object.entries({serviceKey:env.DATA_GO_KR_SERVICE_KEY,pageNo:"1",numOfRows:"10",returnType:"xml"})) endpoint.searchParams.set(key,value);
  try {
    const upstream=await fetch(endpoint,{signal:AbortSignal.timeout(10000),redirect:"error"});
    if(!upstream.ok) return response({ok:false,error:`과기정통부 API 응답 오류 (${upstream.status})`,items:[]},502);
    const text=await upstream.text();
    const code=tag(text,"resultCode")||tag(text,"returnReasonCode");
    if(code && !["00","0"].includes(code)) return response({ok:false,error:`과기정통부 API 코드 ${code}: ${tag(text,"resultMsg")||tag(text,"returnAuthMsg")||"요청 실패"}`,items:[]},502);
    const rows=[...text.matchAll(/<item\b[^>]*>([\s\S]*?)<\/item>/gi)];
    const items=rows.map(([_,block],index)=>{
      const link=tag(block,"viewUrl"),title=tag(block,"subject");
      const item=mapCustomRecord({title,link,pubDate:tag(block,"pressDt"),org:tag(block,"deptName"),id:link||title},index,"과학기술정보통신부 사업공고");
      return item?{...item,id:"msit-"+encodeURIComponent(link||title),field:"기술·R&D",kind:"사업공고"}:null;
    }).filter(Boolean);
    if(!code) return response({ok:false,error:"과기정통부 API 응답 형식 또는 인증 상태를 확인해 주세요.",items:[]},502);
    return response({ok:true,source:"과기정통부",count:items.length,items,updatedAt:new Date().toISOString()});
  } catch { return response({ok:false,error:"과기정통부 API 연결 실패 또는 응답 시간 초과",items:[]},502); }
}
export default {
  async fetch(request, env) {
    const url=new URL(request.url);
    if (request.method==="POST" && url.pathname==="/api/custom-source") return collectCustomSource(request);
    if (request.method!=="GET") return new Response("Method not allowed",{status:405,headers:{allow:"GET, POST"}});
    if (url.pathname==="/api/g2b") return getG2B(env);
    if (url.pathname==="/api/msit") return getMsit(env);
    if (url.pathname==="/api/kstartup") return getKstartup(env);
    if (url.pathname==="/api/customs-trade") return getCustomsTrade(env,url);
    if (url.pathname==="/api/bizinfo/support") return getBizinfo(env,"support");
    if (url.pathname==="/api/bizinfo/events") return getBizinfo(env,"event");
    if (url.pathname==="/api/mcst-rss") return getCultureRss("notice");
    if (url.pathname==="/api/mcst-press-rss") return getCultureRss("press");
    if (url.pathname!=="/") return new Response("Not found",{status:404});
    return new Response(page,{headers:{"content-type":"text/html; charset=utf-8","x-content-type-options":"nosniff","referrer-policy":"strict-origin-when-cross-origin"}});
  },
};
