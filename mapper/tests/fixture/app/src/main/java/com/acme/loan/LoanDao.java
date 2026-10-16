package com.acme.loan;
public class LoanDao {
    public LoanBO findByGlobalAccountNum(String gan) {
        return (LoanBO) session().getNamedQuery(LoanConstants.FIND_BY_GAN).uniqueResult();
    }
    public void save(LoanBO loan) { session().saveOrUpdate(loan); }
    private org.hibernate.Session session() { return null; }
}
