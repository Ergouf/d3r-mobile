// Print a function's decompiled C, callers and callees.
// Usage: -postScript DumpAt.java 0x3c9a70
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class DumpAt extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length == 0) { println("usage: DumpAt.java <address>"); return; }
        Address address = toAddr(args[0]);
        Function f = getFunctionAt(address);
        if (f == null) f = getFunctionContaining(address);
        if (f == null) { println("no function at " + address); return; }
        println("FUNCTION " + f.getName() + " entry=" + f.getEntryPoint());
        println("CALLERS:");
        for (Function caller : f.getCallingFunctions(monitor)) println("  " + caller.getName() + " @" + caller.getEntryPoint());
        println("CALLEES:");
        for (Function callee : f.getCalledFunctions(monitor)) println("  " + callee.getName() + " @" + callee.getEntryPoint());
        DecompInterface ifc = new DecompInterface();
        ifc.openProgram(currentProgram);
        DecompileResults res = ifc.decompileFunction(f, 120, monitor);
        if (res != null && res.decompileCompleted()) {
            println("--- C ---");
            println(res.getDecompiledFunction().getC());
        } else {
            println("decompile failed: " + (res == null ? "null" : res.getErrorMessage()));
        }
        ifc.dispose();
    }
}
