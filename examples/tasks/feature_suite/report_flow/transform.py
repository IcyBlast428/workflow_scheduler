def summarize(rows,region):
    selected=[]
    for row in rows:
        if row['region']!=region:continue
        try:amount=int(row['amount'])
        except (TypeError,ValueError):continue
        if amount<=0:continue
        selected.append(dict(row,amount=amount))
    return selected
