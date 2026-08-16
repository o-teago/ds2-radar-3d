// Pure logic for the DS2 radar — no DOM / no THREE. Shared by radar.html and the tests.
// Loaded in the browser as `RL`, and required by node tests.
(function(root){
  'use strict';

  // memory<->mesh transform (SWAP X<->Z + offset + flip), driven by the `adj` state.
  function xform(adj, x, y, z){
    let px=x, pz=z;
    if(adj.swap){ const t=px; px=pz; pz=t; }
    return { x: px*adj.fx+adj.ox, y: y+adj.oy, z: pz*adj.fz+adj.oz };
  }
  // inverse of xform (mesh point -> game coords), used by click-to-place.
  function unxform(adj, px, py, pz){
    let rx=(px-adj.ox)/adj.fx, rz=(pz-adj.oz)/adj.fz, ry=py-adj.oy;
    if(adj.swap){ const t=rx; rx=rz; rz=t; }
    return { x:rx, y:ry, z:rz };
  }
  // Decide the new "peek" state from the incoming raw game position.
  //   peek : current peekUntilMove (bool)
  //   base : peekBase {x,z} or null  (where the peek started)
  //   prev : previous lastGame {x,z} or null  (position on the last tick)
  //   x,z  : new raw game position
  // While peek is ON the camera does NOT auto-follow/align. It resumes when the
  // player moves. Returns the updated peekUntilMove.
  function resolvePeek(peek, base, prev, x, z){
    if(!peek) return false;
    if(prev && Math.abs(x-prev.x)+Math.abs(z-prev.z) > 50) return false;   // TP / big jump -> resume
    if(!base) return false;                                                // invalid state (peek w/o base) -> recover
    if(Math.abs(x-base.x)+Math.abs(z-base.z) > 1.2) return false;          // walked -> resume
    return true;                                                           // still standing near where peek began
  }

  // Build the info-panel rows for a POI mark: one row per item, pairing each item
  // name with its description (parallel `descs` array). Falls back to the mark
  // label when the pin has no item breakdown. `hasDesc` flags rows worth an
  // expandable (+) toggle. The UI keeps every description collapsed by default.
  function poiRows(mark){
    const items=(mark&&mark.items)||null, ds=(mark&&mark.descs)||[];
    let rows;
    if(items && items.length){
      rows=items.map(function(nm,i){ return { name:nm, desc:(ds[i]||'').trim() }; });
    }else{
      rows=[{ name:(mark&&mark.label)||'', desc:'' }];
    }
    return { rows:rows, hasDesc:rows.some(function(r){ return !!r.desc; }) };
  }

  // Search + rank POIs for the finder panel. Filters by name substring (case-insensitive),
  // then — when the live player position is known — sorts by horizontal distance (nearest
  // first, i.e. "near me"); otherwise alphabetical. Returns [{poi, dist}] capped at `limit`.
  function poiSearch(pois, query, player, limit){
    const q=(query||'').trim().toLowerCase();
    const out=[];
    for(let i=0;i<pois.length;i++){
      const p=pois[i];
      if(q && (p.label||'').toLowerCase().indexOf(q)<0) continue;
      let dist=null;
      if(player){ const dx=p.x-player.x, dz=p.z-player.z; dist=Math.sqrt(dx*dx+dz*dz); }
      out.push({poi:p, dist:dist});
    }
    if(player) out.sort(function(a,b){ return a.dist-b.dist; });
    else out.sort(function(a,b){ return (a.poi.label||'').localeCompare(b.poi.label||''); });
    return (limit && out.length>limit) ? out.slice(0,limit) : out;
  }

  const API={ xform, unxform, resolvePeek, poiRows, poiSearch };
  if(typeof module!=='undefined' && module.exports) module.exports=API;   // node
  root.RL=API;                                                            // browser
})(typeof globalThis!=='undefined'?globalThis:this);
