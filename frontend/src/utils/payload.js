// 补发文件来源可能是轨检车导出的 CSV，撤销标记以文本形式到达；
// 这里只做无损的标量转换，修订号与撤销语义的校验仍在后端完成。
export function parseSupplement(records){
 return records.map(row=>{
  if(!row||typeof row!=='object'||Array.isArray(row))throw new Error('补发记录必须是 JSON 对象数组');
  if(typeof row.revoked!=='string')return row;
  const text=row.revoked.trim().toLowerCase();
  if(['true','1','yes','是','撤销','已撤销'].includes(text))return {...row,revoked:true};
  if(['false','0','no','否','正常','有效',''].includes(text))return {...row,revoked:false};
  return row;
 });
}
