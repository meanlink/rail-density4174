import {datasets} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,notify,date} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';
import {parseSupplement} from '../utils/payload.js';
export async function dataPage(){
 workspace.datasets=await datasets.list();let selected=workspace.datasets[0]?await datasets.get(workspace.datasets[0].id):null,m=workspace.meta;
 return heading('02 / DATA INTAKE','数据接入与批次追溯','保留原始业务字段、来源和内容指纹。补发按缺陷编号与修订号接收：新版替换旧版，撤销点退出分析，重复投递不重复计入。补发前创建的试验始终使用原数据。')+'<div class="dataset-grid"><section class="panel"><div class="section-title"><h2>业务批次</h2><span>'+workspace.datasets.length+' 批</span></div><div class="batch-list">'+workspace.datasets.map(d=>'<button class="batch-item" data-dataset="'+d.id+'"><strong>'+esc(d.name)+'</strong><span>'+d.rows+' 条 · '+esc(d.source)+'</span><small>SHA256 '+esc(d.checksum.slice(0,18))+'…</small></button>').join('')+'</div><div class="section-title"><h2>接入新数据</h2></div><form id="dataset-form"><label>批次名称<input name="name" required minlength="2" placeholder="例如：11 月复测批次"></label><label>上传 CSV 或 JSON<input type="file" id="file-input" accept=".json,.csv"></label><label>记录 JSON<textarea name="records" rows="6" placeholder="粘贴 JSON 数组，或先选择上方文件" required></textarea></label><p class="hint">字段：'+m.columns.map(c=>esc(c.key)+' / '+esc(c.label)).join('，')+'；可选 revision 修订号（缺省为 1）与 revoked 撤销标记。5–5,000 条记录。</p><button type="submit" class="primary" '+(session.user.role==='viewer'?'disabled':'')+'>校验并接入批次</button></form></section><section class="panel"><div class="section-title"><h2 id="preview-name">'+esc(selected?.name||'尚无批次')+'</h2><span>预览前 30 条 · 仅含有效点</span></div><div id="data-preview">'+table(m.columns,selected?.records.slice(0,30)||[])+'</div><div id="supplement-area">'+supplementBlock(selected)+'</div></section></div>';
}
function supplementBlock(d){
 if(!d)return '';
 const logs=(d.supplements||[]);
 const rows=logs.map(s=>({seq:s.kind==='intake'?'原始接入':'补发 #'+(s.id),source:s.source,received:s.received,added:s.added,corrected:s.corrected,revoked:s.revoked,ignored:s.ignored,at:date(s.created_at),actor:s.actor||'—'}));
 const columns=[{key:'seq',label:'投递'},{key:'source',label:'来源'},{key:'received',label:'接收条数'},{key:'added',label:'新增'},{key:'corrected',label:'更正'},{key:'revoked',label:'撤销'},{key:'ignored',label:'忽略'},{key:'at',label:'接收时间'},{key:'actor',label:'操作者'}];
 return '<div class="section-title"><h2>补发与修订台账</h2><span>同一编号同修订冲突时整次拒绝</span></div><div id="supplement-log">'+table(columns,rows,'尚无接收记录。')+'</div><form id="supplement-form"><label>补发来源<input name="source" value="supplement.json" required minlength="1" maxlength="200"></label><label>上传补发 CSV 或 JSON<input type="file" id="supplement-file" accept=".json,.csv"></label><label>补发记录 JSON<textarea name="records" rows="5" placeholder=\'[{"defect_id":"NJ-0001","revision":2,"mileage_km":12.41,"lateral_mm":2.1,"severity":3}]\' required></textarea></label><p class="hint">仅填写变化的点：新点、需要更正的旧点（升修订号）、撤销点（升修订号并写 revoked=true）。与已接收修订完全相同的重复投递会被忽略。当前批次有效点 '+d.rows+' 个。</p><button type="submit" class="primary" '+(session.user.role==='viewer'?'disabled':'')+'>接收本次补发</button></form>';
}
export function bindData(refresh){
 let source='manual.json';
 document.querySelector('#file-input').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;source=file.name;const text=await file.text(),records=file.name.endsWith('.csv')?parseCSV(text):JSON.parse(text);document.querySelector('[name=records]').value=JSON.stringify(records,null,2);}catch(error){notify(error.message,true);}});
 document.querySelectorAll('[data-dataset]').forEach(button=>button.onclick=async()=>{try{const d=await datasets.get(button.dataset.dataset);document.querySelector('#preview-name').textContent=d.name;document.querySelector('#data-preview').innerHTML=table(workspace.meta.columns,d.records.slice(0,30));document.querySelector('#supplement-area').innerHTML=supplementBlock(d);bindSupplement(button.dataset.dataset,refresh);}catch(error){notify(error.message,true);}});
 submit(document.querySelector('#dataset-form'),async f=>{await datasets.create({name:f.get('name'),source,records:JSON.parse(f.get('records'))});notify('数据已接入，可前往工作台执行分析');await refresh();});
 bindSupplement(workspace.datasets[0]?.id,refresh);
}
function bindSupplement(datasetId,refresh){
 const form=document.querySelector('#supplement-form');if(!form||!datasetId)return;
 document.querySelector('#supplement-file').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;const text=await file.text(),records=file.name.endsWith('.csv')?parseSupplement(parseCSV(text)):parseSupplement(JSON.parse(text));form.querySelector('[name=records]').value=JSON.stringify(records,null,2);form.querySelector('[name=source]').value=file.name;}catch(error){notify(error.message,true);}};
 submit(form,async f=>{let parsed;try{parsed=JSON.parse(f.get('records'));}catch(e){throw new Error('补发记录必须是 JSON 数组');}const result=await datasets.supplement(datasetId,{source:f.get('source').trim()||'supplement.json',records:parsed});const s=result.supplement;notify('补发已接收：新增 '+s.added+'，更正 '+s.corrected+'，撤销 '+s.revoked+'，忽略 '+s.ignored);await refresh();});
}
