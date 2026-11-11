// List references to a data address.
// Usage: -postScript XrefsAt.java 0x1876f20
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class XrefsAt extends GhidraScript {
    @Override
    public void run() throws Exception {
        for (String arg : getScriptArgs()) {
            Address a = toAddr(arg);
            println("ADDRESS " + a);
            Reference[] refs = getReferencesTo(a);
            if (refs.length == 0) println("  (no references)");
            for (Reference r : refs) {
                Function f = getFunctionContaining(r.getFromAddress());
                println("  REF " + r.getFromAddress() + " " + (f == null ? "?" : f.getName()));
            }
        }
    }
}
