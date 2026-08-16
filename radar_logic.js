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

  const API={ xform, unxform, resolvePeek };
  if(typeof module!=='undefined' && module.exports) module.exports=API;   // node
  root.RL=API;                                                            // browser
})(typeof globalThis!=='undefined'?globalThis:this);
