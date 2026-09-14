import fs from 'node:fs/promises';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const source = JSON.parse(await fs.readFile('/private/tmp/sociomed-review.EU7W2M/source.json', 'utf8'));
const d = source.data;
const out = '/Users/calvinainebyona/Desktop/sociomed-lean/outputs/catalog_review_20260914';
const wb = Workbook.create();
const productById = new Map(d.products.map(p => [p.product_id, p]));
const invById = new Map(d.inventory.map(p => [p.inventory_id, p]));
const val = value => value == null ? '' : typeof value === 'string' && value.startsWith('=') ? `'${value}` : value;
const number = value => value == null || value === '' ? '' : Number.isFinite(Number(value)) ? Number(value) : value;
const col = n => {let s=''; for(n++;n;n=Math.floor((n-1)/26)) s=String.fromCharCode(65+(n-1)%26)+s; return s;};
const sheets = [];
function table(name, headers, rows, editable = []) {
  const s = wb.worksheets.add(name); sheets.push(name);
  s.showGridLines = false;
  const values = [headers, ...rows.map(row => row.map(val))];
  const last = col(headers.length-1);
  s.getRange(`A1:${last}${values.length}`).values = values;
  s.getRange(`A1:${last}${values.length}`).format.font = {name:'Arial',size:11,color:'#202C39'};
  s.getRange(`A1:${last}${values.length}`).format.columnWidth = 24;
  s.getRange(`A1:${last}${values.length}`).format.rowHeight = 32;
  s.getRange(`A1:${last}${values.length}`).format.wrapText = true;
  s.getRange(`A1:${last}1`).format = {fill:'#263D53',font:{name:'Arial',bold:true,color:'#FFFFFF'},rowHeight:48,wrapText:true};
  if(rows.length) s.tables.add(`A1:${last}${values.length}`,true,`Table${sheets.length}`);
  for(const i of editable) if(rows.length) s.getRange(`${col(i)}2:${col(i)}${values.length}`).format.fill = '#FFF2CC';
  s.freezePanes.freezeRows(1);
  return s;
}
function paired(name, rows, idHeaders, ids, fields, extraHeaders=[], extras=()=>[]) {
  const headers=[...idHeaders]; const edit=[];
  for(const field of fields){headers.push(`Current ${field}`,`Corrected ${field}`); edit.push(headers.length-1);}
  headers.push(...extraHeaders,'Decision','Reviewer note'); edit.push(headers.length-2,headers.length-1);
  const result=rows.map((r,i)=>[...ids(r,i),...fields.flatMap(f=>{
    let current=r[f] ?? ''; if(['page','position','unit_price','min_qty','max_qty','stock_qty','lead_time_days'].includes(f)) current=number(current);
    return [current,current];
  }),...extras(r,i),'Pending','']);
  const sheet=table(name,headers,result,edit);
  if(rows.length) sheet.getRange(`${col(headers.length-2)}2:${col(headers.length-2)}${rows.length+1}`).dataValidation={rule:{type:'list',values:['Pending','Approved','Needs supplier confirmation']}};
  return sheet;
}

const guide=[
 ['Source',source.source,'Local source workbook dated 2026-09-13. Snapshot prepared 2026-09-14.'],
 ['Live comparison','Unavailable','Google authentication/network request failed. This file is not a PostgreSQL export or confirmation of deployed data.'],
 ['How to edit','Yellow columns','Corrected columns begin with current values. Edit them, set Decision, and add a note. Grey/current columns preserve the source.'],
 ['How to apply','Match stable IDs and source row','Copy approved corrections into the original named Google Sheet tab. This review file is not directly imported by the application.'],
 ['Start here','Families, then Menu','Agree family placement and specialty labels before product exceptions, variants and supplier prices.'],
 ['Products',d.products.length,'Product names, family membership and visibility. Missing/blank active means true. False excludes discovery.'],
 ['Inventory',d.inventory.length,'Supplier SKU, brand, UOM, stock and lead time. Product-level SKU/UOM are not the offer source.'],
 ['Pricing',d.pricing.length,'One row per tier. Preserve currency and UOM; compare like packs. Correct missing IDs before sync.'],
 ['Families',d.parent_products.length,'page/position/category_id/department are imported from parent_products. parent_name is review-only; approved product_families.name controls runtime names.'],
 ['Menu',d.browse_menu.length,'CATEGORY nodes lead to SPECIALTY children. Four specialties per message, up to twelve parent families.'],
 ['Attributes',d.product_attributes_review.length,'These are proposed review rows. Map into product_attributes with an approved taxonomy version before the bot uses them.'],
 ['Source notes','Review reasons retained','Existing _review_reason text is copied as evidence; its statements about old code may now be outdated.'],
 ['Not imported','Derived and review tabs','browse_memberships, offer_lines, family_offers, featured_products, family_dict and product_attributes_review remain outside direct imports.'],
 ['Safety','No production edits','No source values, prices or placement have been changed in Google Sheets or PostgreSQL.'],
 ['Verification','Dry run, then real sync','Check skipped-invalid rows and version history before activating corrections. A dry run rolls back everything.'],
 ['Supported currencies','UGX, KES, SSP, RWF, CDF','Use deployed exchange-rate settings. New pricing.currency defaults to UGX when blank/missing.'],
];
const g=table('Start here',['Topic','Value','What to do'],guide);
g.getRange('A1:A17').format.columnWidth=25; g.getRange('B1:B17').format.columnWidth=38; g.getRange('C1:C17').format.columnWidth=95; g.getRange('A2:C17').format.rowHeight=48;
paired('Families',d.parent_products,['Source row','Family ID'],(r,i)=>[i+2,r.product_family_id],['parent_name','category_id','department','page','position'],['Variants in source','Name activation'],r=>[number(r.variant_count),'parent_name is review-only; map approved name to product_families']);
paired('Menu',d.browse_menu,['Source row','Node ID'],(r,i)=>[i+2,r.node_id],['parent_node_id','label','node_type','category_id','department','page','position','next_action']);
paired('Products',d.products,['Source row','Product ID'],(r,i)=>[i+2,r.product_id],['name','product_family_id','category','clinical_speciality','active','related_ids'],['Source variant label','Source review reason'],r=>[r.variant_display,r._review_reason]);
paired('Inventory',d.inventory,['Source row','Inventory ID','Product name'],(r,i)=>[i+2,r.inventory_id,productById.get(r.product_id)?.name],['product_id','vendor_id','sku','brand','uom','stock_qty','lead_time_days'],['Source review reason'],r=>[r._review_reason]);
paired('Pricing',d.pricing,['Source row','Product name','SKU','UOM'],(r,i)=>{const inv=invById.get(r.inventory_id);return [i+2,productById.get(inv?.product_id)?.name,inv?.sku,inv?.uom];},['pricing_id','inventory_id','min_qty','max_qty','unit_price','currency','price_valid_until'],['Proposed source ID','Source review reason'],r=>[r._proposed_pricing_id,r._review_reason]);
paired('Attributes',d.product_attributes_review,['Source row','Product ID','Product name'],(r,i)=>[i+2,r.product_id,productById.get(r.product_id)?.name],['attribute_code','value','unit','approval_status'],['Evidence','Activation requirement'],r=>[r.source,r.review_note]);
paired('Aliases',d.aliases,['Source row'],(r,i)=>[i+2],['product_id','alias']);
const issues=[];
for(const [i,r] of d.pricing.entries()) if(!r.pricing_id) issues.push(['pricing',i+2,r.inventory_id,'Missing pricing_id',r._proposed_pricing_id || '', 'Review proposed ID, then populate pricing_id']);
for(const [i,r] of d.products.entries()) if(String(r.active).toLowerCase()==='false') issues.push(['products',i+2,r.product_id,'Product inactive',r.name,'Confirm it should remain hidden']);
for(const [i,r] of d.parent_products.entries()) if(!r.category_id || !r.department) issues.push(['parent_products',i+2,r.product_family_id,'Incomplete placement',r.parent_name,'Check category_id and department against Menu']);
table('Priority issues',['Source tab','Source row','Record key','Issue','Source proposal or name','Next action'],issues);
console.log(JSON.stringify({counts:Object.fromEntries(sheets.map(n=>[n,wb.worksheets.getItem(n).getUsedRange().values.length-1])),missingPriceIds:d.pricing.filter(r=>!r.pricing_id).length,inactive:d.products.filter(r=>String(r.active).toLowerCase()==='false').length}));
console.log((await wb.inspect({kind:'table',range:'Pricing!A1:H5',tableMaxRows:5,tableMaxCols:8,maxChars:2000})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:10},summary:'Formula error scan'})).ndjson);
for(const name of sheets){
  const preview=await wb.render({sheetName:name,range:name==='Start here'?'A1:C6':'A1:F6',scale:1,format:'png'});
  await fs.writeFile(`${out}/${name.replaceAll(' ','_')}.png`,new Uint8Array(await preview.arrayBuffer()));
}
await (await SpreadsheetFile.exportXlsx(wb)).save(`${out}/SocioMED_catalog_corrections.xlsx`);
