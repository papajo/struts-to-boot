package com.acme.loan;

import org.apache.struts.action.*;

public class LoanAction extends DispatchAction {
    private LoanFacade loanFacade;

    public ActionForward disburse(ActionMapping mapping, ActionForm form, Object request, Object response) {
        LoanForm f = (LoanForm) form;
        loanFacade.disburse(f.getGlobalAccountNum(), f.getAmount());
        return mapping.findForward(Forwards.update_success.toString());
    }

    public ActionForward get(ActionMapping mapping, ActionForm form, Object request, Object response) {
        return mapping.findForward("get_success");
    }
}
