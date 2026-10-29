package ai.lmctl.lmclient;

import com.oracle.svm.core.annotate.Substitute;
import com.oracle.svm.core.annotate.TargetClass;

import java.net.URI;

/**
 * lmclient is a headless CLI: nothing in it opens a browser or a window. Some dependencies still
 * register java.awt.Desktop for reflection (H2's reflect-config does so for its Server class, which
 * opens the web console in a browser). A reflection-registered Desktop.getDesktop()/browse() pulls
 * java.awt.Toolkit into the image, which the build guards against with -H:AbortOnTypeReachable.
 * These substitutions replace the registered entry points with headless answers so the AWT
 * toolkit is never reachable, whichever library registers Desktop.
 */
@TargetClass(className = "java.awt.Desktop")
final class Target_java_awt_Desktop {
    @Substitute
    public static boolean isDesktopSupported() { return false; }

    @Substitute
    public static Target_java_awt_Desktop getDesktop() {
        throw new UnsupportedOperationException("lmclient is headless: java.awt.Desktop is not available");
    }

    @Substitute
    public void browse(URI uri) {
        throw new UnsupportedOperationException("lmclient is headless: cannot open " + uri + " in a browser");
    }
}
