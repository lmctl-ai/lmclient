package ai.lmctl.lmdb;

import com.oracle.svm.core.jdk.NativeLibrarySupport;
import com.oracle.svm.core.jdk.PlatformNativeLibrarySupport;
import com.oracle.svm.hosted.c.NativeLibraries;
import java.nio.file.Path;
import org.graalvm.nativeimage.Platform;
import org.graalvm.nativeimage.hosted.Feature;

/** Link JDBC native engines into the Linux executable instead of extracting shared libraries. */
public final class StaticJdbcFeature implements Feature {
    @Override public void beforeAnalysis(BeforeAnalysisAccess access) {
        if (!Platform.includedIn(Platform.LINUX.class)) return;
        var libraries = NativeLibraries.singleton();
        libraries.getLibraryPaths().add(Path.of("target/static-jni").toAbsolutePath().toString());
        String standardLibraryDirectory = System.getenv("LMDB_STATIC_LIBDIR");
        if (standardLibraryDirectory != null) libraries.getLibraryPaths().add(standardLibraryDirectory);
        register("sqlitejdbc", "org_sqlite_core_NativeDB");
        register("duckdb_java", "org_duckdb");
        libraries.addStaticJniLibrary("sqlitejdbc");
        libraries.addStaticJniLibrary("duckdb_java");
    }
    private static void register(String library,String prefix) {
        NativeLibrarySupport.singleton().preregisterUninitializedBuiltinLibrary(library);
        PlatformNativeLibrarySupport.singleton().addBuiltinPkgNativePrefix(prefix);
    }
}
