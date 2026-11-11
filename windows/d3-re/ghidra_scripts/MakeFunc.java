// Create a function at each address if Ghidra has not defined one.
// Usage: -postScript MakeFunc.java 0x3bad24
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class MakeFunc extends GhidraScript {
    @Override
    public void run() throws Exception {
        for (String arg : getScriptArgs()) {
            Address a = toAddr(arg);
            Function existing = getFunctionAt(a);
            if (existing != null) {
                println("exists " + existing.getName() + " at " + a);
                continue;
            }
            disassemble(a);
            Function f = createFunction(a, null);
            println("created " + (f == null ? "null" : f.getName()) + " at " + a);
        }
    }
}
