// Find UI/action strings and their references in the current program.
// Run through tools/d3-re/ghidra_analyze.ps1.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.Data;
import ghidra.program.model.data.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.symbol.Reference;

public class FindUiRefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        Listing listing = currentProgram.getListing();
        DataIterator it = listing.getDefinedData(true);
        int strings = 0, refs = 0;
        while (it.hasNext()) {
            Data d = it.next();
            Object value;
            try {
                value = d.getValue();
            } catch (Exception e) {
                continue;
            }
            if (!(value instanceof String)) continue;
            String s = (String) value;
            if (!(s.contains("OnClick") || s.contains("Mouseover") || s.contains("OnHotKey")
                    || s.startsWith("UI_") || s.startsWith("UI:") || s.contains("Mouse")
                    || s.contains("ControlScheme") || s.contains("LayoutRoot")
                    || s.contains("LeftClick") || s.contains("RightClick")
                    || s.contains("ActionBinding") || s.contains("KeyBinding"))) {
                continue;
            }
            strings++;
            println("STRING " + d.getMinAddress() + " " + s);
            Reference[] rs = getReferencesTo(d.getMinAddress());
            for (Reference r : rs) {
                refs++;
                Function f = getFunctionContaining(r.getFromAddress());
                println("  REF " + r.getFromAddress() + " " + (f == null ? "?" : f.getName()));
            }
        }
        println("TOTAL strings=" + strings + " refs=" + refs);
    }
}
