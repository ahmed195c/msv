// Field Work Detail — static JS (cached by browser)
// Template sets window.FW_CONFIG = { pk, hasBuildingType } before this file loads.

// ── Static data ───────────────────────────────────────────────────────────────
var LOCATIONS = ["Accommodation","Admin Area","Airport","Animal Basins","Animal Feeding Area","Animal Pot","Animal Shed","Ants Nest","Auditorium","Back Yard","Basement","Basin","Bathroom","Bee Hive","Bins","Bucket","Building","Burrows","Cabinet houses","Ceiling","Channel","Classroom","Clinic Room","Closed Water Tank","Closet","Common Area","Compost Hole","Conference Rm","Construction Site","Corners","Cracks and Crevices","dedicated kitchen","Discarded Tyres","Door / Window Frames","Down Spouts","drainage","Drains/Sinks","Driver's Quarter","Drum","Dumpster Area","Electrical Room","Electricity Chamber","Escort Villa","Etisalat Chambers","exterior perimeter","exterior wallings","Ezzab","Farm(s)","Fence (internal)","Fiber Tank","fixed cabinets","Flats Basin Area","Floor Drain","Flower pots","Forest Area","Fountains","Front Door","Front Yard","Furniture","Garbage Area","Garbage Bin","Garden perimeter","Grounds","Guard House","Gymnasium","Hallways","Hanging Cabinets","Head Quarters","Helper's Quarter","Hole","Horse Barn","Hotel","House (inside)","House (outside)","Industrial Area","Inside the farm","Interior Perimeter","Irrigation Control Valve","Jail","kitchen","Labor Camp","Laboratory Room","Landfill","Laundry Room","Library","Lobby","Locker Room","Maid's Room","Manhole","Manhole in the house/villa","Manhole in the streets","Manholes","Market Area","Masjid","Office","Office Room","Open Water Tank","Palace","Palm Tree Burrows","Pantry","Pantry Closet","Park","Parking Area","Patio","Pheromone Trap","Pipe(s)","Playground","Pond","Pool","Port","Poultry","Prayer Room","Reception","Real Estate","Rodent Bait Station","Roof Top","Scrap","Security Room","Septic Tank","Sewage Manhole","Shed /Storage unit","Shooting Ranges","Shop","Sink Cabinets","Stagnant Water","Steel cabinets","Storage","Store Room","Storm Drain","Storm Water Lines","Swimming Pool","Tank","Teachers Room","Tent","Theater","toilet/bath/washroom","Trash Bins","Trees","TV","under shelves","Underground Water Tank","Villa/House","VIP building","Wadi","walls","Waste Area","Waste Room","Water Accumulation","Water Cooler","Window Frames","Wooden cabinets"];

var PEST_CATS = [
  {lbl:'🔴 DANGEROUS PEST', pests:['Bees','Scorpion','Snake','Poisonous Spider','Wasp And Bee','Other Harmful Pest']},
  {lbl:'🟡 NUISANCE PEST',  pests:['Ants','German Cockroach','American Cockroach','Lizard','Termites','Non Poisonous Spider','Drain Flies','Fruit Flies']},
  {lbl:'🟠 VECTOR PEST',    pests:['Mosquito Adult','Mosquito Aedes','Mosquito Culex','Mosquito Anopheles','Rodents Roof Rat','Rodents Norway Rat','Rodents House mouse','House Flies']},
  {lbl:'⚪ OTHERS',         pests:['Agricultural Pest']}
];

var PESTICIDES = [
  {n:"Actellic 50 EC",u:"ML"},{n:"ECOLARVACIDE EC",u:"ML"},{n:"Starycide SC 480",u:"ML"},
  {n:"DIFRON 25 SC",u:"ML"},{n:"GRAYBATE 50 SG",u:"ML"},{n:"BIOPREN 4 GR",u:"ML"},
  {n:"LAROXYFEN PLUS WT",u:"ML"},{n:"Aqua k-Othrine",u:"ML"},{n:"Chirotox",u:"ML"},
  {n:"TETRACON 50 EC",u:"ML"},{n:"KULCYPERIN 100/3 EC",u:"ML"},{n:"DEMON MAX INSECTICIDE",u:"ML"},
  {n:"Solfac EC 50",u:"ML"},{n:"CYMPERATOR 25 EC",u:"ML"},{n:"Bio Amplat",u:"ML"},
  {n:"ROTRYN 200",u:"ML"},{n:"GUADIN SE",u:"ML"},{n:"BAITFURAN SP",u:"GRM"},
  {n:"Detral Super",u:"ML"},{n:"K-Othrine Partix",u:"ML"},{n:"PERMETHOR",u:"GRM"},
  {n:"Temprid SC",u:"ML"},{n:"HYMENOPHTHOR GR",u:"GRM"},{n:"Vertox Oktablok",u:"GRM"},
  {n:"FACORAT PELLETS",u:"GRM"},{n:"VICTOR V FAST-KILL BRAND BLOCKS II",u:"GRM"},
  {n:"SUREFIRE ALL WEATHER BLOCKS",u:"GRM"},{n:"PROTECT SENSATION 2IN1",u:"GRM"},
  {n:"VERTOX PASTA BAIT",u:"GRM"},{n:"STELLIOX D50",u:"GRM"},{n:"TALON WB",u:"GRM"},
  {n:"SUREFIRE BROMA BLOCKS RODENTICIDE",u:"GRM"},{n:"NOCURAT PARAFFINATO",u:"GRM"},
  {n:"BuyBlocker Snake Deter",u:"GRM"},{n:"BOOM",u:"ML"},{n:"CYPFORCE 40 EC",u:"ML"},
  {n:"D-TETRASUPER EC",u:"ML"},{n:"TEMEPHOS 55EC",u:"ML"}
];

var ACTIONS_LIST = [
  'Applied Gel Bait','Residual Spraying','ULV Fogging','Drain Treatment',
  'Installed Glue Trap','Installed Bait Station','Area Cleaned','Advised Cleaning',
  'Sealed Entry Point','Water Removed','Follow-up Required','Monitoring Continued',
  'No Action Required','Chemical Treatment Done','Trap Replaced',
  'Deep Cleaning Required','Maintenance Required','Pest Control Treatment Completed'
];

var FINDINGS_LIST = [
  'Standing water','Water in plant pots','AC water leakage','Open water containers',
  'Blocked drains','Water on roof/balcony','Dirty floor drains','Uncovered tanks',
  'Gaps under doors','Open food storage','Garbage accumulation','Cluttered storage',
  'Holes in walls','Dirty kitchen area','Open drainage points','Feeding birds/cats',
  'Open garbage bins','Food waste','Dirty drains','Bad housekeeping','Rotten materials',
  'Dirty bin area','Water leakage','Strong bad odor','Dirty kitchen',
  'Grease accumulation','Cracks and gaps','Food residues','Wet areas','Cluttered area'
];

// ── Helpers ───────────────────────────────────────────────────────────────────
function T(ar,en){return (document.documentElement.getAttribute('data-lang')||'ar')==='ar'?ar:en;}
function applyT(el,ar,en){el.setAttribute('data-ar-txt',ar);el.setAttribute('data-en-txt',en);el.textContent=T(ar,en);}

// ── Combo box ─────────────────────────────────────────────────────────────────
var _dropStyle = 'display:none;position:absolute;z-index:300;width:100%;max-height:200px;overflow-y:auto;background:#fff;border:1.5px solid #cbd5e1;border-top:none;border-radius:0 0 8px 8px;margin:0;padding:0;list-style:none;box-shadow:0 4px 16px rgba(0,0,0,.12);';
var _liStyle   = 'padding:9px 14px;cursor:pointer;font-size:12.5px;border-bottom:1px solid #f1f5f9;color:#0f172a;';

function initCombo(inp, ul, items, getLabel, onSelect) {
  var idx = -1;
  function render(q) {
    var ql = q.trim().toLowerCase();
    var hits = ql ? items.filter(function(it){ return getLabel(it).toLowerCase().indexOf(ql) !== -1; }) : [];
    if (!hits.length) { ul.style.display = 'none'; return; }
    ul.innerHTML = ''; idx = -1;
    hits.forEach(function(it, i) {
      var li = document.createElement('li');
      li.textContent = getLabel(it);
      li.style.cssText = _liStyle;
      li.addEventListener('mousedown', function(e){ e.preventDefault(); inp.value = getLabel(it); if(onSelect) onSelect(it); ul.style.display='none'; });
      li.addEventListener('mouseenter', function(){ hi(i); });
      ul.appendChild(li);
    });
    ul.style.display = 'block';
  }
  function hi(i) {
    ul.querySelectorAll('li').forEach(function(l){ l.style.background=''; });
    idx = i;
    var el = ul.querySelectorAll('li')[i];
    if (el) { el.style.background='#eff6ff'; el.scrollIntoView({block:'nearest'}); }
  }
  inp.addEventListener('input', function(){ render(inp.value); });
  inp.addEventListener('focus', function(){ if(inp.value) render(inp.value); });
  inp.addEventListener('blur',  function(){ setTimeout(function(){ ul.style.display='none'; },150); });
  inp.addEventListener('keydown', function(e) {
    var lis = ul.querySelectorAll('li');
    if (e.key==='ArrowDown') { e.preventDefault(); hi(Math.min(idx+1,lis.length-1)); }
    else if (e.key==='ArrowUp') { e.preventDefault(); hi(Math.max(idx-1,0)); }
    else if (e.key==='Enter' && idx>=0 && ul.style.display!=='none') { e.preventDefault(); lis[idx].dispatchEvent(new Event('mousedown')); }
    else if (e.key==='Escape') { ul.style.display='none'; }
  });
}

function makeDrop(){ var ul=document.createElement('ul'); ul.style.cssText=_dropStyle; return ul; }

// ── Pesticide row ─────────────────────────────────────────────────────────────
function addPesticideRow(container, data) {
  data = data || {};
  var row = document.createElement('div');
  row.className = 'pst-row';
  row.style.cssText = 'display:flex;gap:6px;margin-bottom:8px;align-items:flex-start;position:relative;';

  var nWrap = document.createElement('div');
  nWrap.style.cssText = 'flex:1;position:relative;';
  var nInp = document.createElement('input');
  nInp.type='text'; nInp.autocomplete='off';
  nInp.setAttribute('data-ar-ph','اسم المبيد…'); nInp.setAttribute('data-en-ph','Pesticide name…');
  nInp.placeholder=T('اسم المبيد…','Pesticide name…');
  nInp.className='form-control pst-name'; nInp.style.cssText='font-size:12.5px;';
  nInp.value = data.name || '';
  var nUl = makeDrop();
  nWrap.appendChild(nInp); nWrap.appendChild(nUl);

  var qInp = document.createElement('input');
  qInp.type='number'; qInp.min='0'; qInp.step='0.1';
  qInp.setAttribute('data-ar-ph','الكمية'); qInp.setAttribute('data-en-ph','Qty');
  qInp.placeholder=T('الكمية','Qty');
  qInp.className='form-control pst-qty'; qInp.style.cssText='width:85px;font-size:12.5px;';
  qInp.value = data.qty || '';

  var uSel = document.createElement('select');
  uSel.className='form-control pst-unit'; uSel.style.cssText='width:72px;font-size:12.5px;';
  ['ML','GRM'].forEach(function(u){
    var o=document.createElement('option'); o.value=u; o.textContent=u;
    if((data.unit||'ML')===u) o.selected=true;
    uSel.appendChild(o);
  });

  var rm = document.createElement('button');
  rm.type='button'; rm.textContent='×';
  rm.style.cssText='width:32px;height:36px;background:#fee2e2;color:#991b1b;border:none;border-radius:6px;cursor:pointer;font-size:16px;flex-shrink:0;';
  rm.addEventListener('click', function(){ row.remove(); });

  row.appendChild(nWrap); row.appendChild(qInp); row.appendChild(uSel); row.appendChild(rm);
  container.appendChild(row);

  initCombo(nInp, nUl, PESTICIDES, function(p){ return p.n; }, function(p){ uSel.value = p.u; });
}

// ── Spray entry card ──────────────────────────────────────────────────────────
var _cardCount = 0;

function createCard(data) {
  data = data || {};
  var n = ++_cardCount;
  var card = document.createElement('div');
  card.className = 'spray-entry-card';
  card.style.cssText = 'background:#fff;border:1.5px solid #e2e8f0;border-radius:12px;margin-bottom:12px;overflow:visible;';

  var hdr = document.createElement('div');
  hdr.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:9px 14px;background:#f1f5f9;border-bottom:1px solid #e2e8f0;border-radius:12px 12px 0 0;';
  var htitle = document.createElement('span');
  htitle.className = 'card-num';
  htitle.style.cssText = 'font-size:13px;font-weight:700;color:#374151;display:inline-flex;gap:4px;';
  var htLbl = document.createElement('span'); applyT(htLbl,'موقع رش','Spray Location');
  var htNum = document.createElement('span'); htNum.className='card-num-n'; htNum.textContent='#'+n;
  htitle.appendChild(htLbl); htitle.appendChild(htNum);
  var rmCard = document.createElement('button');
  rmCard.type='button'; applyT(rmCard,'× حذف','× Delete');
  rmCard.style.cssText='padding:3px 10px;font-size:11px;background:#fee2e2;color:#991b1b;border:1px solid #fca5a5;border-radius:6px;cursor:pointer;';
  rmCard.addEventListener('click', function(){ card.remove(); renumber(); });
  hdr.appendChild(htitle); hdr.appendChild(rmCard);
  card.appendChild(hdr);

  var body = document.createElement('div');
  body.style.cssText = 'padding:14px;';

  // location
  var locWrap = document.createElement('div');
  locWrap.style.cssText = 'margin-bottom:12px;position:relative;';
  var locLbl = document.createElement('label');
  locLbl.style.cssText = 'font-size:12px;font-weight:600;color:#374151;display:block;margin-bottom:4px;';
  applyT(locLbl,'المكان','Location');
  var locInp = document.createElement('input');
  locInp.type='text'; locInp.autocomplete='off';
  locInp.setAttribute('data-ar-ph','ابحث أو اكتب…'); locInp.setAttribute('data-en-ph','Search or type…');
  locInp.placeholder=T('ابحث أو اكتب…','Search or type…');
  locInp.className='form-control loc-inp'; locInp.value = data.location||'';
  var locUl = makeDrop();
  locWrap.appendChild(locLbl); locWrap.appendChild(locInp); locWrap.appendChild(locUl);
  body.appendChild(locWrap);
  initCombo(locInp, locUl, LOCATIONS, function(l){ return l; }, null);

  // infestation level
  var infWrap = document.createElement('div');
  infWrap.style.cssText = 'margin-bottom:12px;padding:12px 14px;background:#fff7ed;border:1.5px solid #fed7aa;border-radius:10px;';
  var infLbl = document.createElement('div');
  infLbl.style.cssText = 'font-size:12px;font-weight:700;color:#374151;margin-bottom:8px;';
  applyT(infLbl,'مستوى الإصابة','Infestation Level');
  infWrap.appendChild(infLbl);
  var INF_OPTS = [
    {val:'no_infestation',      ar:'لا يوجد إصابة',      en:'No Infestation',      color:'#dcfce7', border:'#86efac'},
    {val:'low_infestation',     ar:'إصابة خفيفة',        en:'Low Infestation',     color:'#fef9c3', border:'#fde047'},
    {val:'moderate_infestation',ar:'إصابة متوسطة',       en:'Moderate Infestation',color:'#ffedd5', border:'#fdba74'},
    {val:'high_infestation',    ar:'إصابة شديدة',        en:'High Infestation',    color:'#fee2e2', border:'#fca5a5'},
  ];
  var infGroup = document.createElement('div');
  infGroup.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;';
  INF_OPTS.forEach(function(opt){
    var lbl = document.createElement('label');
    lbl.style.cssText = 'display:inline-flex;align-items:center;gap:5px;padding:5px 12px;border:1.5px solid #e2e8f0;border-radius:20px;background:#fff;font-size:12.5px;cursor:pointer;user-select:none;transition:border-color .12s,background .12s;';
    var cb = document.createElement('input');
    cb.type='radio'; cb.name='infestation_'+n; cb.value=opt.val; cb.className='inf-cb';
    if((data.infestation||'') === opt.val){ cb.checked=true; lbl.style.background=opt.color; lbl.style.borderColor=opt.border; }
    cb.addEventListener('change', function(){
      infGroup.querySelectorAll('label').forEach(function(l){ l.style.background='#fff'; l.style.borderColor='#e2e8f0'; });
      if(cb.checked){ lbl.style.background=opt.color; lbl.style.borderColor=opt.border; }
    });
    var txt = document.createElement('span');
    applyT(txt, opt.ar, opt.en);
    lbl.appendChild(cb); lbl.appendChild(txt);
    infGroup.appendChild(lbl);
  });
  infWrap.appendChild(infGroup);
  body.appendChild(infWrap);

  // pests
  var pestWrap = document.createElement('div');
  pestWrap.style.cssText = 'margin-bottom:12px;padding:12px 14px;background:#f8fafc;border:1.5px solid #e2e8f0;border-radius:10px;';
  var pestLbl = document.createElement('div');
  pestLbl.style.cssText = 'font-size:12px;font-weight:700;color:#374151;margin-bottom:8px;';
  applyT(pestLbl,'الحشرات الموجودة','Pests Found');
  pestWrap.appendChild(pestLbl);
  var existPests = data.pests || [];
  PEST_CATS.forEach(function(cat){
    var catHd = document.createElement('div');
    catHd.style.cssText = 'font-size:10.5px;font-weight:700;color:#6b7280;letter-spacing:.06em;text-transform:uppercase;margin:8px 0 5px;padding-bottom:3px;border-bottom:1px solid #e5e7eb;';
    catHd.textContent = cat.lbl;
    pestWrap.appendChild(catHd);
    var catGroup = document.createElement('div');
    catGroup.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;margin-bottom:4px;';
    cat.pests.forEach(function(pestName){
      var lbl = document.createElement('label');
      lbl.style.cssText = 'display:inline-flex;align-items:center;gap:5px;padding:5px 11px;border:1.5px solid #e2e8f0;border-radius:20px;background:#fff;font-size:12.5px;cursor:pointer;user-select:none;transition:border-color .12s,background .12s;';
      var cb = document.createElement('input');
      cb.type='checkbox'; cb.value=pestName; cb.className='pest-cb';
      if(existPests.indexOf(pestName)!==-1){ cb.checked=true; lbl.style.background='#eff6ff'; lbl.style.borderColor='#2563eb'; }
      cb.addEventListener('change', function(){
        lbl.style.background = cb.checked?'#eff6ff':'#fff';
        lbl.style.borderColor = cb.checked?'#2563eb':'#e2e8f0';
      });
      lbl.appendChild(cb); lbl.appendChild(document.createTextNode(pestName));
      catGroup.appendChild(lbl);
    });
    pestWrap.appendChild(catGroup);
  });
  body.appendChild(pestWrap);

  // pesticides
  var pstWrap = document.createElement('div');
  var pstLbl = document.createElement('div');
  pstLbl.style.cssText = 'font-size:12px;font-weight:600;color:#374151;margin-bottom:6px;';
  applyT(pstLbl,'المبيدات المستخدمة','Pesticides Used');
  var pstRows = document.createElement('div');
  pstRows.className = 'pst-rows';
  var pstData = data.pesticides || [];
  if (pstData.length) {
    pstData.forEach(function(p){ addPesticideRow(pstRows, p); });
  } else {
    addPesticideRow(pstRows, {});
  }
  var addPstBtn = document.createElement('button');
  addPstBtn.type='button'; applyT(addPstBtn,'+ إضافة مبيد','+ Add Pesticide');
  addPstBtn.style.cssText='padding:6px 13px;font-size:12px;font-weight:600;background:#eff6ff;color:#2563eb;border:1.5px solid #bfdbfe;border-radius:7px;cursor:pointer;margin-top:4px;';
  addPstBtn.addEventListener('click', function(){ addPesticideRow(pstRows, {}); });
  pstWrap.appendChild(pstLbl); pstWrap.appendChild(pstRows); pstWrap.appendChild(addPstBtn);
  body.appendChild(pstWrap);

  // actions taken
  var actWrap = document.createElement('div');
  actWrap.style.cssText = 'margin-top:12px;padding:12px 14px;background:#f0fdf4;border:1.5px solid #bbf7d0;border-radius:10px;';
  var actLbl = document.createElement('div');
  actLbl.style.cssText = 'font-size:12px;font-weight:700;color:#374151;margin-bottom:8px;';
  applyT(actLbl,'الإجراءات المتخذة','Actions Taken');
  actWrap.appendChild(actLbl);
  var actGroup = document.createElement('div');
  actGroup.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;';
  var existActions = data.actions || [];
  ACTIONS_LIST.forEach(function(actName){
    var lbl = document.createElement('label');
    lbl.style.cssText = 'display:inline-flex;align-items:center;gap:5px;padding:5px 11px;border:1.5px solid #d1fae5;border-radius:20px;background:#fff;font-size:12.5px;cursor:pointer;user-select:none;transition:border-color .12s,background .12s;';
    var cb = document.createElement('input');
    cb.type='checkbox'; cb.value=actName; cb.className='action-cb';
    if(existActions.indexOf(actName)!==-1){ cb.checked=true; lbl.style.background='#dcfce7'; lbl.style.borderColor='#16a34a'; }
    cb.addEventListener('change', function(){
      lbl.style.background = cb.checked?'#dcfce7':'#fff';
      lbl.style.borderColor = cb.checked?'#16a34a':'#d1fae5';
    });
    lbl.appendChild(cb); lbl.appendChild(document.createTextNode(actName));
    actGroup.appendChild(lbl);
  });
  actWrap.appendChild(actGroup);
  body.appendChild(actWrap);

  card.appendChild(body);
  return card;
}

function renumber() {
  document.querySelectorAll('.spray-entry-card .card-num-n').forEach(function(el, i){
    el.textContent = '#' + (i+1);
  });
}

function serializeEntries() {
  var entries = [];
  document.querySelectorAll('.spray-entry-card').forEach(function(card){
    var pests = [];
    card.querySelectorAll('.pest-cb:checked').forEach(function(cb){ pests.push(cb.value); });
    var pesticides = [];
    card.querySelectorAll('.pst-row').forEach(function(row){
      var nm = (row.querySelector('.pst-name')||{value:''}).value.trim();
      var qty = (row.querySelector('.pst-qty')||{value:''}).value.trim();
      var unit = (row.querySelector('.pst-unit')||{value:'ML'}).value;
      if (nm) pesticides.push({name:nm, qty:qty, unit:unit});
    });
    var infCb = card.querySelector('.inf-cb:checked');
    var actions = [];
    card.querySelectorAll('.action-cb:checked').forEach(function(cb){ actions.push(cb.value); });
    entries.push({
      location: (card.querySelector('.loc-inp')||{value:''}).value.trim(),
      pests: pests,
      pesticides: pesticides,
      infestation: infCb ? infCb.value : '',
      actions: actions
    });
  });
  return entries;
}

// ── Init: building type ───────────────────────────────────────────────────────
(function(){
  var cfg = window.FW_CONFIG || {};
  var BT_KEY = 'fw_btype_' + cfg.pk;
  var grp = document.getElementById('bld-type-group');
  if (!grp) return;

  function applyBtStyle(lbl, active){
    lbl.style.background = active ? '#dcfce7' : '#f8fafc';
    lbl.style.borderColor = active ? '#16a34a' : '#e2e8f0';
  }

  if (!cfg.hasBuildingType) {
    try {
      var saved = sessionStorage.getItem(BT_KEY);
      if (saved) {
        grp.querySelectorAll('input[name="building_type"]').forEach(function(r){
          if (r.value === saved) { r.checked = true; applyBtStyle(r.closest('label'), true); }
        });
      }
    } catch(e) {}
  }

  grp.addEventListener('change', function(e){
    if(e.target.name !== 'building_type') return;
    grp.querySelectorAll('label').forEach(function(l){ applyBtStyle(l, false); });
    applyBtStyle(e.target.closest('label'), true);
    try { sessionStorage.setItem(BT_KEY, e.target.value); } catch(e) {}
  });

  var supForm = document.querySelector('form[data-role="supervisor-form"]');
  if (supForm) {
    supForm.addEventListener('submit', function(){
      try { sessionStorage.removeItem(BT_KEY); } catch(e) {}
    });
  }
})();

// ── Init: spray entries ───────────────────────────────────────────────────────
(function(){
  var cfg = window.FW_CONFIG || {};
  var DRAFT_KEY = 'fw_spray_draft_' + cfg.pk;
  var entriesList = document.getElementById('spray-entries-list');
  if (!entriesList) return;

  var existing = JSON.parse(document.getElementById('existing-spray-data').textContent || '[]');
  if (existing.length) {
    existing.forEach(function(e){ entriesList.appendChild(createCard(e)); });
    try { sessionStorage.removeItem(DRAFT_KEY); } catch(e) {}
  } else {
    var draft = null;
    try { draft = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || 'null'); } catch(e) {}
    if (draft && draft.length) {
      draft.forEach(function(e){ entriesList.appendChild(createCard(e)); });
    } else {
      entriesList.appendChild(createCard({}));
    }
  }

  entriesList.addEventListener('input', function(){
    try { sessionStorage.setItem(DRAFT_KEY, JSON.stringify(serializeEntries())); } catch(e) {}
  });
  entriesList.addEventListener('change', function(){
    try { sessionStorage.setItem(DRAFT_KEY, JSON.stringify(serializeEntries())); } catch(e) {}
  });

  var addBtn = document.getElementById('add-spray-entry-btn');
  if (addBtn) {
    addBtn.addEventListener('click', function(){
      var c = createCard({});
      entriesList.appendChild(c);
      c.scrollIntoView({behavior:'smooth', block:'center'});
      try { sessionStorage.setItem(DRAFT_KEY, JSON.stringify(serializeEntries())); } catch(e) {}
    });
  }

  var form = document.querySelector('form[data-role="supervisor-form"]');
  if (form) {
    form.addEventListener('submit', function(){
      document.getElementById('spray-entries-json').value = JSON.stringify(serializeEntries());
      try { sessionStorage.removeItem(DRAFT_KEY); } catch(e) {}
    });
  }
})();

// ── Init: findings ────────────────────────────────────────────────────────────
(function(){
  var group = document.getElementById('report-findings-group');
  if (!group) return;
  var el = document.getElementById('existing-findings-data');
  var existFindings = JSON.parse(el ? el.textContent : '[]');

  FINDINGS_LIST.forEach(function(name){
    var lbl = document.createElement('label');
    lbl.style.cssText = 'display:inline-flex;align-items:center;gap:5px;padding:5px 11px;border:1.5px solid #fde68a;border-radius:20px;background:#fff;font-size:12.5px;cursor:pointer;user-select:none;transition:border-color .12s,background .12s;';
    var cb = document.createElement('input');
    cb.type = 'checkbox'; cb.value = name; cb.className = 'report-finding-cb';
    if (existFindings.indexOf(name) !== -1) { cb.checked = true; lbl.style.background='#fef9c3'; lbl.style.borderColor='#ca8a04'; }
    cb.addEventListener('change', function(){
      lbl.style.background = cb.checked ? '#fef9c3' : '#fff';
      lbl.style.borderColor = cb.checked ? '#ca8a04' : '#fde68a';
    });
    lbl.appendChild(cb); lbl.appendChild(document.createTextNode(name));
    group.appendChild(lbl);
  });

  var supForm = document.querySelector('form[data-role="supervisor-form"]');
  if (supForm) {
    supForm.addEventListener('submit', function(){
      var checked = [];
      document.querySelectorAll('.report-finding-cb:checked').forEach(function(cb){ checked.push(cb.value); });
      document.getElementById('report-findings-json').value = JSON.stringify(checked);
    });
  }
})();

// ── Init: signature pads ──────────────────────────────────────────────────────
(function(){
  function initPad(id) {
    var canvas = document.getElementById(id + '-sig-canvas');
    var hidden = document.getElementById(id + '-sig-data');
    if (!canvas || !hidden) return;
    var ctx = canvas.getContext('2d');
    var drawing = false;
    var lastX = 0, lastY = 0;
    var hasDrawn = false;

    function pos(e) {
      var r = canvas.getBoundingClientRect();
      var scaleX = canvas.width / r.width;
      var scaleY = canvas.height / r.height;
      var src = e.touches ? e.touches[0] : e;
      return [(src.clientX - r.left) * scaleX, (src.clientY - r.top) * scaleY];
    }
    function start(e) {
      e.preventDefault(); drawing = true;
      var p = pos(e); lastX = p[0]; lastY = p[1];
      ctx.beginPath(); ctx.moveTo(lastX, lastY);
    }
    function move(e) {
      if (!drawing) return;
      e.preventDefault();
      var p = pos(e);
      ctx.lineWidth = 2.2; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#1e293b';
      ctx.lineTo(p[0], p[1]); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(p[0], p[1]);
      lastX = p[0]; lastY = p[1]; hasDrawn = true;
    }
    function end(e) {
      if (!drawing) return;
      drawing = false;
      if (hasDrawn) hidden.value = canvas.toDataURL('image/png');
    }
    canvas.addEventListener('mousedown', start);
    canvas.addEventListener('mousemove', move);
    canvas.addEventListener('mouseup', end);
    canvas.addEventListener('mouseleave', end);
    canvas.addEventListener('touchstart', start, {passive:false});
    canvas.addEventListener('touchmove', move, {passive:false});
    canvas.addEventListener('touchend', end);
  }

  initPad('client');
  initPad('supervisor');

  window.clearSig = function(id) {
    var canvas = document.getElementById(id + '-sig-canvas');
    var hidden = document.getElementById(id + '-sig-data');
    if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
    if (hidden) hidden.value = '';
  };
})();

// ── Init: image drop zones ────────────────────────────────────────────────────
(function(){
  function initDrop(dropId, inputId, prevId, statusId) {
    var zone   = document.getElementById(dropId);
    var input  = document.getElementById(inputId);
    var prev   = document.getElementById(prevId);
    var status = document.getElementById(statusId);
    if (!zone || !input) return;

    zone.addEventListener('dragover', function(e){ e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', function(){ zone.classList.remove('drag-over'); });
    zone.addEventListener('drop', function(e){
      e.preventDefault(); zone.classList.remove('drag-over');
      var dt = e.dataTransfer;
      if (dt && dt.files.length) { input.files = dt.files; renderPreviews(input.files); }
    });
    input.addEventListener('change', function(){ renderPreviews(input.files); });

    function renderPreviews(files) {
      if (!files || !files.length) {
        if (prev) { prev.style.display = 'none'; prev.innerHTML = ''; }
        if (status) status.style.display = 'none';
        return;
      }
      prev.innerHTML = '';
      Array.from(files).forEach(function(file) {
        var item = document.createElement('div');
        item.className = 'img-preview-item';
        var img = document.createElement('img');
        img.src = URL.createObjectURL(file);
        img.onload = function(){ URL.revokeObjectURL(img.src); };
        item.appendChild(img);
        prev.appendChild(item);
      });
      prev.style.display = 'flex';
      var n = files.length;
      status.textContent = n === 1 ? ('تم اختيار: ' + files[0].name) : ('تم اختيار ' + n + ' صور');
      status.style.display = 'block';
    }
  }

  initDrop('drop-closure',       'inp-closure',        'prev-closure',        'status-closure');
  initDrop('drop-report-photos', 'inp-report-photos',  'prev-report-photos',  'status-report-photos');
})();

// ── Init: GPS location ────────────────────────────────────────────────────────
(function(){
  var btn = document.getElementById('btn-get-location');
  if (!btn) return;
  btn.addEventListener('click', function(){
    var status = document.getElementById('loc-status');
    status.style.display = 'inline';
    status.textContent = 'جاري تحديد الموقع…';
    btn.disabled = true;
    navigator.geolocation.getCurrentPosition(
      function(pos){
        document.getElementById('loc-lat').value = pos.coords.latitude;
        document.getElementById('loc-lng').value = pos.coords.longitude;
        status.textContent = 'تم تحديد الموقع — جاري الحفظ…';
        document.getElementById('location-form').submit();
      },
      function(){
        status.style.color = '#b91c1c';
        status.textContent = 'تعذّر تحديد الموقع. تأكد من منح صلاحية الموقع.';
        btn.disabled = false;
      },
      {enableHighAccuracy: true, timeout: 10000}
    );
  });
})();
