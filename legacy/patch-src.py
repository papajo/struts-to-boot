#!/usr/bin/env python3
"""Runtime-compat source patches for Mifos on Jetty 9.4 (applied to a copy inside the Docker build).

Each patch is an exact (file, old, new) replacement and fails loudly if the source moved.
Only environment-compat fixes belong here; never change business behaviour.

1. UrlHelper.constructCurrentPageUrl: deleteCharAt(servletPath.indexOf('/')) throws
   StringIndexOutOfBounds when the originating servlet path has no '/' (Jetty 9.4 hands the
   Spring "cheetah" servlet such paths on Struts->FTL forwards). Every loan page and the error
   page itself died with a 500 via BackUrlInterceptor. Guard the delete (2 sites in the file).
2. QueryIntroductionAdvisor.matches: rejects any class named "com.*". On Java 6/7 JDK proxies
   were named "$ProxyNN"; Java 8 names them "com.sun.proxy.$ProxyNN". The DAO targets are
   JDK-proxied (tx), so the finder introduction never applied and every generated
   `retrieve*` DAO call failed ("object is not an instance of declaring class") — e.g.
   loanAccountAction.do#get via the questionnaire EventSourceDao. Restore the Java 6 match.
3. AccountStatusActionForm.accountRecords: List getter + auto-growing indexed accessors. Java 8's
   Introspector no longer pairs them into an IndexedPropertyDescriptor (List isn't an array),
   so BeanUtils calls list.get/set(i) on the empty list -> IndexOutOfBounds in
   statussearchresults.jsp and on ChangeAccountStatus.do#update populate. Back the field with
   a list that grows the same way the indexed accessors do ("" padding), including lists
   handed to setAccountRecords(List) (AccountStatusAction.searchResults passes a plain ArrayList).
4. LoanRepaymentTag.setIsNewGropLoan(Boolean): loanRepayment.jsp passes "${isNewGropLoan}", unset
   for non-GLIM loans. EL 2.x (Jetty 6/Tomcat 6) coerced null to Boolean.FALSE; EL 3.0 (Jetty 9.4)
   passes null, and `if (isNewGropLoan)` unboxes it -> NPE -> 500 on every
   loanAccountAction.do#getLoanRepaymentSchedule, which also kills the flow (next steps "Page expired").
   Same List+indexed pattern exists in LoanAccountActionForm (clients, fees, custom fields):
   patch those only when a recording shows the failure.
"""
import sys
from pathlib import Path

PATCHES = [
    ("userInterface/src/main/java/org/mifos/ui/core/controller/util/helpers/UrlHelper.java",
     """        StringBuilder url = new StringBuilder(originatingServletPath).append("?").append(originatingQueryString).deleteCharAt(originatingServletPath.indexOf('/'));""",
     """        StringBuilder url = new StringBuilder(originatingServletPath).append("?").append(originatingQueryString);
        int slash = originatingServletPath.indexOf('/');   // struts-to-boot: Jetty 9.4 compat
        if (slash >= 0) {
            url.deleteCharAt(slash);
        }"""),
    ("common/src/main/java/org/mifos/platform/persistence/QueryIntroductionAdvisor.java",
     """        if (clazz.getName().startsWith("com.")) {""",
     """        if (clazz.getName().startsWith("com.sun.proxy.")) {   // struts-to-boot: Java 8 proxy names
            return true;
        }

        if (clazz.getName().startsWith("com.")) {"""),
    ("application/src/main/java/org/mifos/accounts/loan/struts/actionforms/AccountStatusActionForm.java",
     """    private List<String> accountRecords;
""",
     """    private List<String> accountRecords;

    /** struts-to-boot: Java 8 Introspector compat; grows like getAccountRecords(int)/setAccountRecords(int,..). */
    private static class GrowingList extends ArrayList<String> {
        private static final long serialVersionUID = 1L;
        @Override
        public String get(int i) {
            while (i >= size()) {
                add("");
            }
            return super.get(i);
        }
        @Override
        public String set(int i, String v) {
            while (i >= size()) {
                add("");
            }
            return super.set(i, v);
        }
    }
"""),
    ("application/src/main/java/org/mifos/accounts/loan/struts/actionforms/AccountStatusActionForm.java",
     """accountRecords = new ArrayList<String>();""",
     """accountRecords = new GrowingList();"""),
    # AccountStatusAction.searchResults calls setAccountRecords(new ArrayList<String>()) before the JSP
    ("application/src/main/java/org/mifos/accounts/loan/struts/actionforms/AccountStatusActionForm.java",
     """        this.accountRecords = accountRecords;
""",
     """        if (accountRecords == null || accountRecords instanceof GrowingList) {
            this.accountRecords = accountRecords;
        } else {
            this.accountRecords = new GrowingList();
            this.accountRecords.addAll(accountRecords);
        }
"""),
    ("application/src/main/java/org/mifos/accounts/loan/struts/uihelpers/LoanRepaymentTag.java",
     """        this.isNewGropLoan = isNewGropLoan;""",
     """        this.isNewGropLoan = isNewGropLoan != null && isNewGropLoan;   // struts-to-boot: EL 3.0 null coercion"""),
]

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
for rel, old, new in PATCHES:
    p = root / rel
    s = p.read_text()
    if new in s:
        print(f"patch-src: already applied {rel}")
        continue
    n = s.count(old)
    if n == 0:
        raise SystemExit(f"patch-src: anchor not found in {rel}")
    p.write_text(s.replace(old, new))
    print(f"patch-src: patched {rel} ({n} site{'s' if n > 1 else ''})")
