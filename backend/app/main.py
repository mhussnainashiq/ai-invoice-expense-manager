from datetime import date, timedelta
from collections import defaultdict
import csv, io, os
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from .database import Base, engine, get_db
from . import models, schemas
from .security import hash_password, verify_password, create_token, current_user

Base.metadata.create_all(bind=engine)
app = FastAPI(title="AI Invoice & Expense Manager API", version="1.0.0")
origins = [os.getenv("FRONTEND_ORIGIN", "http://localhost:5173"), "http://127.0.0.1:5173"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def invoice_total(inv):
    subtotal = sum(item.quantity * item.unit_price for item in inv.items)
    taxable = max(0, subtotal - inv.discount)
    return round(taxable + taxable * inv.tax_rate / 100, 2)

def paid_total(inv):
    return round(sum(p.amount for p in inv.payments), 2)

def invoice_dict(inv):
    total = invoice_total(inv)
    paid = paid_total(inv)
    status_value = inv.status
    if status_value != "Draft":
        if paid >= total and total > 0: status_value = "Paid"
        elif paid > 0: status_value = "Partially Paid"
        elif inv.due_date < date.today(): status_value = "Overdue"
    return {"id": inv.id, "client_id": inv.client_id, "client_name": inv.client.name if inv.client else "Unassigned",
            "number": inv.number, "issue_date": inv.issue_date.isoformat(), "due_date": inv.due_date.isoformat(),
            "status": status_value, "tax_rate": inv.tax_rate, "discount": inv.discount, "notes": inv.notes,
            "items": [{"id": i.id, "description": i.description, "quantity": i.quantity, "unit_price": i.unit_price} for i in inv.items],
            "subtotal": round(sum(i.quantity*i.unit_price for i in inv.items),2), "total": total,
            "paid": paid, "balance": round(max(0,total-paid),2)}

@app.get("/api/health")
def health():
    return {"status": "ok", "ai_configured": bool(os.getenv("OPENAI_API_KEY"))}

@app.post("/api/auth/register", status_code=201)
def register(data: schemas.RegisterIn, db: Session = Depends(get_db)):
    email = data.email.lower()
    if db.query(models.User).filter(models.User.email == email).first():
        raise HTTPException(409, "An account with this email already exists")
    user = models.User(name=data.name.strip(), email=email, password_hash=hash_password(data.password))
    db.add(user); db.commit(); db.refresh(user)
    return {"access_token": create_token(user.id), "token_type": "bearer", "user": {"id": user.id, "name": user.name, "email": user.email, "currency": user.currency}}

@app.post("/api/auth/login")
def login(data: schemas.LoginIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == data.email.lower()).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect")
    return {"access_token": create_token(user.id), "token_type": "bearer", "user": {"id": user.id, "name": user.name, "email": user.email, "currency": user.currency}}

@app.get("/api/auth/me")
def me(user: models.User = Depends(current_user)):
    return {"id": user.id, "name": user.name, "email": user.email, "currency": user.currency}

@app.get("/api/clients")
def clients(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return [{"id": c.id, "name": c.name, "business_name": c.business_name, "email": c.email, "phone": c.phone, "address": c.address} for c in db.query(models.Client).filter_by(user_id=user.id).order_by(models.Client.id.desc()).all()]

@app.post("/api/clients", status_code=201)
def create_client(data: schemas.ClientIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    c = models.Client(user_id=user.id, **data.model_dump()); db.add(c); db.commit(); db.refresh(c)
    return {"id": c.id, **data.model_dump()}

@app.put("/api/clients/{client_id}")
def update_client(client_id: int, data: schemas.ClientIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    c = db.query(models.Client).filter_by(id=client_id, user_id=user.id).first()
    if not c: raise HTTPException(404, "Client not found")
    for k,v in data.model_dump().items(): setattr(c,k,v)
    db.commit(); db.refresh(c)
    return {"id": c.id, **data.model_dump()}

@app.delete("/api/clients/{client_id}", status_code=204)
def delete_client(client_id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    c = db.query(models.Client).filter_by(id=client_id, user_id=user.id).first()
    if not c: raise HTTPException(404, "Client not found")
    if c.invoices: raise HTTPException(409, "This client has invoices. Reassign or remove them first.")
    db.delete(c); db.commit()

@app.get("/api/invoices")
def invoices(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    rows = db.query(models.Invoice).options(joinedload(models.Invoice.client), joinedload(models.Invoice.items), joinedload(models.Invoice.payments)).filter_by(user_id=user.id).order_by(models.Invoice.id.desc()).all()
    return [invoice_dict(x) for x in rows]

@app.post("/api/invoices", status_code=201)
def create_invoice(data: schemas.InvoiceIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    if data.client_id and not db.query(models.Client).filter_by(id=data.client_id,user_id=user.id).first(): raise HTTPException(400,"Invalid client")
    if db.query(models.Invoice).filter_by(user_id=user.id, number=data.number).first(): raise HTTPException(409,"Invoice number already exists")
    inv = models.Invoice(user_id=user.id, client_id=data.client_id, number=data.number, issue_date=data.issue_date, due_date=data.due_date, status=data.status, tax_rate=data.tax_rate, discount=data.discount, notes=data.notes)
    inv.items = [models.InvoiceItem(**i.model_dump()) for i in data.items]
    db.add(inv); db.commit(); db.refresh(inv)
    return invoice_dict(db.query(models.Invoice).options(joinedload(models.Invoice.client),joinedload(models.Invoice.items),joinedload(models.Invoice.payments)).filter_by(id=inv.id).first())

@app.put("/api/invoices/{invoice_id}")
def update_invoice(invoice_id: int, data: schemas.InvoiceIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    inv = db.query(models.Invoice).options(joinedload(models.Invoice.items),joinedload(models.Invoice.payments),joinedload(models.Invoice.client)).filter_by(id=invoice_id,user_id=user.id).first()
    if not inv: raise HTTPException(404,"Invoice not found")
    if data.client_id and not db.query(models.Client).filter_by(id=data.client_id,user_id=user.id).first(): raise HTTPException(400,"Invalid client")
    duplicate = db.query(models.Invoice).filter(models.Invoice.user_id==user.id, models.Invoice.number==data.number, models.Invoice.id!=invoice_id).first()
    if duplicate: raise HTTPException(409,"Invoice number already exists")
    for k in ["client_id","number","issue_date","due_date","status","tax_rate","discount","notes"]: setattr(inv,k,getattr(data,k))
    inv.items.clear(); db.flush()
    for item in data.items: inv.items.append(models.InvoiceItem(**item.model_dump()))
    db.commit()
    inv = db.query(models.Invoice).options(joinedload(models.Invoice.client),joinedload(models.Invoice.items),joinedload(models.Invoice.payments)).filter_by(id=invoice_id,user_id=user.id).first()
    return invoice_dict(inv)

@app.delete("/api/invoices/{invoice_id}", status_code=204)
def delete_invoice(invoice_id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    inv = db.query(models.Invoice).filter_by(id=invoice_id,user_id=user.id).first()
    if not inv: raise HTTPException(404,"Invoice not found")
    db.delete(inv); db.commit()

@app.post("/api/invoices/{invoice_id}/payments", status_code=201)
def add_payment(invoice_id: int, data: schemas.PaymentIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    inv = db.query(models.Invoice).options(joinedload(models.Invoice.items),joinedload(models.Invoice.payments),joinedload(models.Invoice.client)).filter_by(id=invoice_id,user_id=user.id).first()
    if not inv: raise HTTPException(404,"Invoice not found")
    balance = invoice_total(inv) - paid_total(inv)
    if data.amount > balance + 0.001: raise HTTPException(400, f"Payment exceeds outstanding balance ({balance:.2f})")
    db.add(models.Payment(invoice_id=invoice_id, **data.model_dump())); db.commit()
    inv = db.query(models.Invoice).options(joinedload(models.Invoice.client),joinedload(models.Invoice.items),joinedload(models.Invoice.payments)).filter_by(id=invoice_id,user_id=user.id).first()
    return invoice_dict(inv)

@app.get("/api/expenses")
def expenses(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return [{"id":e.id,"name":e.name,"amount":e.amount,"date":e.date.isoformat(),"category":e.category,"vendor":e.vendor,"payment_method":e.payment_method,"notes":e.notes} for e in db.query(models.Expense).filter_by(user_id=user.id).order_by(models.Expense.date.desc()).all()]

@app.post("/api/expenses", status_code=201)
def create_expense(data: schemas.ExpenseIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    e = models.Expense(user_id=user.id, **data.model_dump()); db.add(e); db.commit(); db.refresh(e)
    return {"id":e.id,"name":e.name,"amount":e.amount,"date":e.date.isoformat(),"category":e.category,"vendor":e.vendor,"payment_method":e.payment_method,"notes":e.notes}

@app.put("/api/expenses/{expense_id}")
def update_expense(expense_id: int, data: schemas.ExpenseIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    e=db.query(models.Expense).filter_by(id=expense_id,user_id=user.id).first()
    if not e: raise HTTPException(404,"Expense not found")
    for k,v in data.model_dump().items(): setattr(e,k,v)
    db.commit()
    return {"id":e.id,"name":e.name,"amount":e.amount,"date":e.date.isoformat(),"category":e.category,"vendor":e.vendor,"payment_method":e.payment_method,"notes":e.notes}

@app.delete("/api/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    e=db.query(models.Expense).filter_by(id=expense_id,user_id=user.id).first()
    if not e: raise HTTPException(404,"Expense not found")
    db.delete(e); db.commit()

@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    invs=db.query(models.Invoice).options(joinedload(models.Invoice.client),joinedload(models.Invoice.items),joinedload(models.Invoice.payments)).filter_by(user_id=user.id).all()
    exps=db.query(models.Expense).filter_by(user_id=user.id).all()
    total_income=round(sum(p.amount for i in invs for p in i.payments),2)
    total_expense=round(sum(e.amount for e in exps),2)
    outstanding=round(sum(max(0,invoice_total(i)-paid_total(i)) for i in invs if i.status!="Draft"),2)
    overdue=round(sum(max(0,invoice_total(i)-paid_total(i)) for i in invs if i.status!="Draft" and i.due_date<date.today() and paid_total(i)<invoice_total(i)),2)
    months=[]
    today=date.today()
    for offset in range(5,-1,-1):
        month=(today.month-1-offset)%12+1
        year=today.year-(1 if today.month-1-offset<0 else 0) if offset < today.month else today.year-1
        start=date(year,month,1)
        end=date(year+1,1,1) if month==12 else date(year,month+1,1)
        income=sum(p.amount for i in invs for p in i.payments if start<=p.paid_at<end)
        expense=sum(e.amount for e in exps if start<=e.date<end)
        months.append({"month":start.strftime("%b"),"income":round(income,2),"expenses":round(expense,2)})
    cats=defaultdict(float)
    for e in exps: cats[e.category]+=e.amount
    return {"income":total_income,"expenses":total_expense,"outstanding":outstanding,"overdue":overdue,"profit":round(total_income-total_expense,2),
            "monthly":months,"categories":[{"category":k,"amount":round(v,2)} for k,v in sorted(cats.items(),key=lambda x:-x[1])],
            "recent_expenses":[{"id":e.id,"name":e.name,"amount":e.amount,"date":e.date.isoformat(),"category":e.category} for e in sorted(exps,key=lambda x:x.date,reverse=True)[:5]],
            "upcoming_invoices":[{"id":i.id,"number":i.number,"client_name":i.client.name if i.client else "Unassigned","due_date":i.due_date.isoformat(),"balance":round(max(0,invoice_total(i)-paid_total(i)),2)} for i in sorted(invs,key=lambda x:x.due_date) if i.status!="Draft" and i.due_date>=today and paid_total(i)<invoice_total(i)][:5]}

@app.post("/api/ai/categorize")
def categorize(payload: dict, user: models.User = Depends(current_user)):
    name = str(payload.get("name","")).strip()
    if not name: raise HTTPException(400,"Provide an expense name")
    key=name.lower()
    mapping={"travel":["uber","taxi","flight","hotel","train","fuel","petrol"],"software":["software","subscription","hosting","domain","cloud","saas","github","openai"],"utilities":["electric","water","internet","phone","utility"],"office supplies":["stationery","paper","printer","office supplies"],"marketing":["ads","advertising","marketing","campaign"],"food":["restaurant","lunch","dinner","coffee","food"],"equipment":["laptop","monitor","keyboard","equipment"]}
    suggestion=next((cat for cat,terms in mapping.items() if any(term in key for term in terms)),"Other")
    if os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
            client=OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=10)
            response=client.chat.completions.create(model=os.getenv("OPENAI_MODEL","gpt-4o-mini"),messages=[{"role":"system","content":"Categorize a business expense. Return only one category from: Travel, Software, Utilities, Office Supplies, Marketing, Food, Equipment, Professional Services, Taxes, Other."},{"role":"user","content":name}],max_tokens=20)
            suggestion=response.choices[0].message.content.strip().title()
            return {"category":suggestion,"source":"ai"}
        except Exception:
            pass
    return {"category":suggestion.title(),"source":"rules","message":"Rule-based suggestion; review before saving."}

@app.post("/api/ai/assistant")
def assistant(payload: schemas.AskIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    invs=db.query(models.Invoice).options(joinedload(models.Invoice.items),joinedload(models.Invoice.payments),joinedload(models.Invoice.client)).filter_by(user_id=user.id).all()
    exps=db.query(models.Expense).filter_by(user_id=user.id).all()
    context={"currency":user.currency,"invoice_count":len(invs),"expense_count":len(exps),
             "paid_income":round(sum(p.amount for i in invs for p in i.payments),2),
             "expenses_total":round(sum(e.amount for e in exps),2),
             "outstanding":round(sum(max(0,invoice_total(i)-paid_total(i)) for i in invs if i.status!="Draft"),2),
             "overdue_invoices":[{"number":i.number,"balance":round(max(0,invoice_total(i)-paid_total(i)),2),"due_date":str(i.due_date)} for i in invs if i.status!="Draft" and i.due_date<date.today() and paid_total(i)<invoice_total(i)]}
    if os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
            client=OpenAI(api_key=os.getenv("OPENAI_API_KEY"),timeout=15)
            result=client.chat.completions.create(model=os.getenv("OPENAI_MODEL","gpt-4o-mini"),messages=[
                {"role":"system","content":"You are a cautious financial assistant. Answer only from the supplied JSON facts. Never invent numbers; if the facts do not answer the question, say what is missing. Clarify that this is not tax or accounting advice."},
                {"role":"user","content":f"User question: {payload.question}\nVerified database facts: {context}"}],max_tokens=400)
            return {"answer":result.choices[0].message.content,"source":"openai","facts":context}
        except Exception:
            pass
    q=payload.question.lower()
    if "expense" in q or "spend" in q: answer=f"Recorded expenses total {context['currency']} {context['expenses_total']:.2f} across {context['expense_count']} expense records."
    elif "income" in q or "earned" in q: answer=f"Recorded payments received total {context['currency']} {context['paid_income']:.2f}."
    elif "overdue" in q: answer=f"There are {len(context['overdue_invoices'])} overdue unpaid invoices in your records."
    elif "outstanding" in q or "unpaid" in q: answer=f"Outstanding invoice balances total {context['currency']} {context['outstanding']:.2f}."
    else: answer=f"I can summarize your recorded figures: income {context['currency']} {context['paid_income']:.2f}, expenses {context['currency']} {context['expenses_total']:.2f}, outstanding {context['currency']} {context['outstanding']:.2f}. Add an OpenAI API key for conversational answers."
    return {"answer":answer,"source":"database-summary","facts":context}

@app.get("/api/reports/export")
def export_csv(kind: str = "expenses", db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    output=io.StringIO()
    writer=csv.writer(output)
    if kind=="invoices":
        writer.writerow(["number","client","issue_date","due_date","status","total","paid","balance"])
        rows=db.query(models.Invoice).options(joinedload(models.Invoice.client),joinedload(models.Invoice.items),joinedload(models.Invoice.payments)).filter_by(user_id=user.id).all()
        for i in rows:
            d=invoice_dict(i); writer.writerow([d["number"],d["client_name"],d["issue_date"],d["due_date"],d["status"],d["total"],d["paid"],d["balance"]])
    else:
        writer.writerow(["name","amount","date","category","vendor","payment_method","notes"])
        rows=db.query(models.Expense).filter_by(user_id=user.id).all()
        for e in rows: writer.writerow([e.name,e.amount,e.date,e.category,e.vendor,e.payment_method,e.notes])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]),media_type="text/csv",headers={"Content-Disposition":f"attachment; filename={kind}.csv"})
