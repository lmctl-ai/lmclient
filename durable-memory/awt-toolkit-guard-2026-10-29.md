# The AWT Toolkit guard and the Desktop substitution (2026-10-29)

The native build aborts if `java.awt.Toolkit` becomes reachable
(`-H:AbortOnTypeReachable=java.awt.Toolkit` in pom.xml): a headless CLI must
not drag AWT, its native libraries and their startup cost into the image.
The guard was green at 0.2.0 and started failing after the protocol areas
landed. The trace report said only "manually created constant".

## Root cause

A diagnostic build without the guard, with `-H:+PrintAnalysisCallTree` and
`-H:+PrintImageObjectTree`, showed the entry points:

- `java.awt.Desktop.browse(URI)` as a reflection root method, and
  `Desktop.getDesktop()` / `Desktop.isDesktopSupported()` as roots added by a
  conditional registration ("manually triggered rescan").
- `Desktop.getDesktop()` calls `Toolkit.getDefaultToolkit()`, which reaches
  `Toolkit`, `sun.awt.HeadlessToolkit`, `EventQueue`, `Component` and the
  rest of AWT.

The registration comes from H2's own `META-INF/native-image/reflect-config.json`:
it registers those three `java.awt.Desktop` methods with the condition
`typeReachable: org.h2.tools.Server` (the H2 web console opens a browser).
`org.h2.tools.Server implements Runnable`; it became reachable through a
saturated `Runnable.run()` call site once the full area class path was
present, so the condition fired. Bytecode scans of every dependency confirm
only two direct `Toolkit` users exist (H2 `GUIConsole`, Angus `image_gif`),
and neither method is reachable; the path was Desktop.

Things that did not fix it, now known: excluding the angus
`native-image.properties` files (the features are not involved), and
broadening the H2 `--exclude-config` regexes (the entry still fired). The
GraalVM reachability-metadata repository configs the plugin adds through
`-H:ConfigurationFileDirectories` register no AWT classes.

## Fix

`src/native/java/ai/lmctl/lmclient/HeadlessSubstitutions.java` substitutes the
three registered `java.awt.Desktop` entry points with headless behaviour:
`isDesktopSupported()` returns false, `getDesktop()` and `browse()` throw
`UnsupportedOperationException`. Whatever library registers Desktop for
reflection, nothing in the image can reach `Toolkit` through it. With the
substitution the guarded analysis completes locally (GraalVM CE 25.0.2,
17,140 reachable types, no abort); the H2 exclusion and the stripped
`lmclient-h2/reflect-config.json` stay as they were.

## How to diagnose the next one

1. Build once without the guard and with
   `-H:+PrintAnalysisCallTree -H:+PrintImageObjectTree`
   (20 minutes; reports under `target/reports/`).
2. In `call_tree_*.txt`, find the `entry ... java.awt.*` lines; `root method`
   means a reflection registration, `manually triggered rescan` a conditional
   one. Walk the tree upwards from the first `Toolkit.getDefaultToolkit` call.
3. Grep every config source the build sees: jar `META-INF/native-image/**`,
   `target/graalvm-reachability-metadata/**`, our `src/main/resources`.
4. Prefer a substitution of the registered entry point over config
   exclusion: exclusions only reach jar resources, not the repository
   configs, and conditional entries can fire later as the class path grows.
