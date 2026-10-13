# Deadlock Dolly 0.6.46-alpha

Compatibility update for Deadlock build 6779 (October 13, 2026).

- **Before:** the game update changed the module identities and several private
  addresses used by Dolly. **After:** reviewed startup, replay-camera, Follow,
  audio, effects, particle, and Players scene profiles recognize build 6779.
- **Before:** new intro-state numbers and a moved hero-component field invalidated
  saved replay/HUD checks. **After:** those checks use the verified current game
  definitions, including the updated controller initialization span.
- **Before:** the Free Cam damage/death and screen-particle filter had no reviewed
  entry for recent builds. **After:** build 6779 has its own verified controller,
  render-call and screen-option entry; POV and unrelated effects keep normal behavior.
- **Before:** the experimental native prop probe relied on a common byte prefix.
  **After:** it is restricted to its previously reviewed build. The supported
  Object Picker continues to use its existing proxy objects.

The bundled unlocker was rebuilt with the exact reviewed tier0/server pair.
Existing reviewed module support and secure-mode/cleanup guards are retained.
The DX11 export-startup fix from 0.6.45 remains included.

This update does not add a new capture backend or native game-model prop creation.
