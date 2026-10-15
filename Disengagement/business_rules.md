# Business Rules

sc_engagement
- 'Shortcode' - client unique identifier
- 'Engagement Date' to 'Disengagement Date' shows the timeline of an employees work assignment
  - if there is no 'Disengagement Date' then the employee is actively working with that client

seat_churn_raw
- by joining 'Shortcode', 'Username', 'Engagement ID', 'Engagement Date', 'Disengagement' date from sc_engagement to comprable columns in seat_churn_raw we can bring over ('UBER Ticket', 'UBER Vol/Inv', 'UBER Type Reason', 'UBER Main Reason') which contains values for reason of disengagement. Joiing seat_churn to sc_engagement should not create duplicates rows


