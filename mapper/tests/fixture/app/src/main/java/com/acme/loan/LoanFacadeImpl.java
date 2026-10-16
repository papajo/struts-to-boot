package com.acme.loan;

import java.util.List;

public class LoanFacadeImpl implements LoanFacade {
    private final LoanDao loanDao = new LoanDao();

    @Override
    public void disburse(String gan, String amount) {
        LoanBO loan = loanDao.findByGlobalAccountNum(gan);
        loan.disburse(amount).post();
        loanDao.save(loan);
    }
}
