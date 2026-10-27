import re
from datetime import datetime
import pandas as pd
import requests
import streamlit as st
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

st.set_page_config(page_title='Customer Signal', page_icon='📡', layout='wide')
st.title('📡 Customer Signal')
st.caption('Evidence-backed customer feedback intelligence · MVP 0.1')

THEMES = {
    'Login & access': ['login', 'log in', 'sign in', 'password', 'browser', 'chrome', 'account', 'verify', 'verification', 'locked out'],
    'Rewards & points': ['reward', 'star', 'points', 'bonus', 'birthday', 'challenge', 'tier'],
    'Ordering & pickup': ['order', 'pickup', 'pick up', 'store', 'location', 'menu', 'ready', 'wait'],
    'Payment & balance': ['pay', 'payment', 'card', 'balance', 'reload', 'refund', 'charged'],
    'App reliability': ['crash', 'freeze', 'slow', 'glitch', 'bug', 'loading', 'update', 'doesn\'t work', 'not working'],
}
RECOMMENDATIONS = {
    'Login & access': 'Investigate sign-in failures by device and browser; add clear recovery guidance.',
    'Rewards & points': 'Make reward eligibility and progress more transparent; audit failed rewards.',
    'Ordering & pickup': 'Audit store selection and pickup estimates; make order status clearer.',
    'Payment & balance': 'Improve payment-error recovery and balance refresh reliability.',
    'App reliability': 'Prioritize reproducible crash/freeze bugs by affected app version.',
}

def analyze(df):
    analyzer = SentimentIntensityAnalyzer()
    df = df.copy()
    df['text'] = df['text'].fillna('').astype(str)
    df = df[df['text'].str.strip().ne('')]
    df['sentiment_score'] = df['text'].map(lambda t: analyzer.polarity_scores(t)['compound'])
    df['sentiment'] = df['sentiment_score'].map(lambda x: 'Positive' if x >= .05 else ('Negative' if x <= -.05 else 'Neutral'))
    def detect(t):
        t = t.lower()
        return [theme for theme, keywords in THEMES.items() if any(re.search(r'(?<!\w)'+re.escape(k)+r'(?!\w)', t) for k in keywords)] or ['Other']
    df['themes'] = df['text'].map(detect)
    return df

st.sidebar.header('Data source')
source = st.sidebar.radio('Choose input', ['Starbucks App Store (public Apple RSS)', 'Upload CSV'], index=0)
brand = st.sidebar.text_input('Brand', 'Starbucks')
product = st.sidebar.text_input('Product', 'Starbucks mobile app')
st.sidebar.caption('This first version supports Apple public review feeds or uploaded feedback, not arbitrary website scraping.')
raw = None
if source.startswith('Starbucks'):
    st.info('Fetching a limited sample of public US App Store reviews. Availability, ordering and completeness depend on Apple’s public feed.')
    if st.button('Fetch and analyze reviews', type='primary'):
        rows=[]
        try:
            for page in range(1, 4):
                url=f'https://itunes.apple.com/us/rss/customerreviews/page={page}/id=331177714/sortby=mostrecent/json'
                response=requests.get(url, timeout=15, headers={'User-Agent':'CustomerSignalMVP/0.1'})
                response.raise_for_status()
                entries=response.json().get('feed',{}).get('entry',[])
                for e in entries:
                    if 'im:rating' not in e: continue
                    rows.append({'date':e.get('updated',{}).get('label','')[:10], 'rating':int(e['im:rating']['label']), 'text':e.get('content',{}).get('label',''), 'title':e.get('title',{}).get('label',''), 'source':'Apple App Store', 'url':e.get('link',{}).get('attributes',{}).get('href',url)})
            if not rows: st.error('No reviews returned. Try CSV upload.'); st.stop()
            raw=pd.DataFrame(rows).drop_duplicates(subset=['date','text'])
            st.session_state['reviews']=raw
        except Exception as ex:
            st.error(f'Public feed unavailable: {ex}. Use CSV upload instead.')
else:
    upload=st.file_uploader('Upload a CSV with a text column (optional: date, rating, source, url)',type='csv')
    if upload:
        raw=pd.read_csv(upload)
        if 'text' not in raw.columns: st.error('CSV needs a text column.'); st.stop()
        st.session_state['reviews']=raw

if 'reviews' in st.session_state:
    df=analyze(st.session_state['reviews'])
    if df.empty: st.warning('No usable feedback'); st.stop()
    for col,default in [('date',''),('rating',None),('source','Uploaded CSV'),('url','')]:
        if col not in df.columns: df[col]=default
    st.subheader(f'{brand} · {product}')
    st.caption(f'{len(df)} accessible reviews analyzed. Not a representative sample of all customers. Sentiment uses VADER, a lightweight rule-based model; theme tagging uses keywords and needs human review.')
    a,b,c=st.columns(3)
    a.metric('Reviews analyzed',len(df))
    b.metric('Negative sentiment',f"{(df.sentiment.eq('Negative').mean()*100):.0f}%")
    ratings=pd.to_numeric(df.rating,errors='coerce')
    c.metric('Average sampled rating',f'{ratings.mean():.2f}/5' if ratings.notna().any() else 'N/A')
    st.subheader('Sentiment distribution')
    st.bar_chart(df.sentiment.value_counts())
    st.subheader('Customer issues and potential actions')
    issue_rows=[]
    for theme in THEMES:
        subset=df[df.themes.map(lambda x:theme in x)]
        if subset.empty:continue
        issue_rows.append({'Theme':theme,'Mentions':len(subset),'Negative mentions':int(subset.sentiment.eq('Negative').sum()),'Potential action':RECOMMENDATIONS[theme]})
    issues=pd.DataFrame(issue_rows)
    if not issues.empty:
        issues=issues.sort_values(['Negative mentions','Mentions'],ascending=False)
        st.dataframe(issues,hide_index=True,use_container_width=True)
        st.caption('A review may match multiple themes. Suggested actions are hypotheses, not validated root causes.')
    st.subheader('Inspect source evidence')
    selected=st.selectbox('Theme',['All']+list(THEMES))
    view=df if selected=='All' else df[df.themes.map(lambda x:selected in x)]
    st.dataframe(view[['date','rating','sentiment','text','source','url']],hide_index=True,use_container_width=True)
    st.download_button('Download analyzed reviews',df.drop(columns=['themes']).to_csv(index=False).encode(),file_name='customer_signal_analysis.csv',mime='text/csv')
else:
    st.markdown('**Start by fetching public Starbucks app reviews or uploading a review CSV.**')
