import utils
from datetime import date, timedelta, datetime
import urllib
import time
import feedparser
from unidecode import unidecode
from semanticscholar import SemanticScholar
from tqdm import tqdm
import os
from scholarly import scholarly, ProxyGenerator
import bibtexparser
from bibtexparser.bwriter import BibTexWriter
from bibtexparser.bibdatabase import BibDatabase
import arxiv
from googlesearch import search as google_search_module
import requests
import traceback
import glob

import traceback
class LitrevTools():

    def __init__(self, api_key=None, arxiv_cats=None, arxiv_max_results=10000, folder=None):

        self.folder = folder

        self.SCH = SemanticScholar(retry=False) # TODO retry or not?
        self.scraper_api_key = api_key

        #self.scraper_api_key = 'TODO os env'#os.path.expanduser('~/SCRAPER_API_KEY.txt')

        if api_key is not None:
            pg = ProxyGenerator()
            print('ScraperAPI set up? : ', pg.ScraperAPI(api_key))
            try:
                scholarly.use_proxy(pg)
            except:
                scholarly.use_proxy(pg, pg)

        self.arxiv_cats = arxiv_cats if arxiv_cats is not None else ["cs.LG", "stat.ML", "stat.ME", "math.ST","econ.EM","stat.AP"]
        self.arxiv_max_results = arxiv_max_results

    def find_on_semantic_scholar(self, title):
        results = utils.try_multiple_times(self.SCH.search_paper, title, limit=1)
        if len(results) > 0:
            return results[0]
        else:
            return None

    def _get_fields_from_pub(self, pub, fields='citationStyles'):
        id = pub['paperId']
        r = utils.try_multiple_times(requests.post, 'https://api.semanticscholar.org/graph/v1/paper/batch', params={'fields': fields}, json={'ids': [id]})
        r =  r.json()
        if len(r) == 0:
            raise NotImplementedError
        return r[0]
    
    def process_title(self, title):
        return title.lower().strip(' .-')

    def purge_duplicates(self, papers):
        get_title = (lambda i: papers[i]) if isinstance(papers[0], str) else (lambda i: papers[i]['title'])
        i = 0
        while i < len(papers):
            title1 = get_title(i)
            j = i+1
            while j < len(papers):
                title2 = get_title(j)
                if self.process_title(title1) == self.process_title(title2):
                    del papers[j]
                else:
                    j += 1
            i += 1
        return papers

    def filter_titles(self, papers, keywords=None):
        papers_filtered = []
        for paper in papers:
            title = paper if isinstance(paper, str) else paper['title']
            if self._filter_entry(title, keywords=keywords):
                papers_filtered.append(paper)

        self.purge_duplicates(papers_filtered)
        return papers_filtered
    
    def citation_count(self, title, semantic_only=True):

        citation_count = None
        publication_date = None
        gscholar_year = None
        semantic_year = None

        if isinstance(title, dict):

            citation_count =  title['citationCount']
            publication_date = title['publicationDate']
            semantic_year = str(title['year'])

        elif semantic_only:

            paper = self.find_on_semantic_scholar(title)
            citation_count =  paper['citationCount']
            publication_date = paper['publicationDate']
            semantic_year = str(paper['year'])


        else:

            # Citation count : try with GScholar first
            print(f'Citation count: Trying "{title}" with Google Scholar.')
            pub = utils.try_multiple_times(scholarly.search_single_pub, title)
            if pub is not None and self._check_title_match(title, pub['bib']['title']):
                pub = utils.try_multiple_times(scholarly.fill, pub)
                citation_count = pub['num_citations']
                gscholar_year = str(pub['bib']['pub_year'])
                print('Citation count retrieved!')
            
            # Publication date : try with arXiV first
            print(f'Citation count: Trying "{title}" with arXiv.')
            result = self.search_arxiv(title)
            if result is not None and self._check_title_match(title, result.title):
                publication_date = result.published.strftime('%Y-%m-%d').split('T')[0]
                print('Publication date retrieved!')

            # Try with Semantic Scholar if something is missing
            if citation_count is None or publication_date is None:
                print(f'Citation count: Trying "{title}" with Semantic Scholar.')
                paper = self.find_on_semantic_scholar(title)
                if paper is not None and self._check_title_match(title, paper['title']):
                    if citation_count is None:
                        citation_count =  paper['citationCount']
                        print('Citation count retrieved!')
                    if publication_date is None:
                        publication_date = paper['publicationDate']
                        print('Publication date retrieved!')
                    semantic_year = str(paper['year'])

        # If still no publication date : impute as YYYY-01-01, if year is available (from GScholar first, then Semantic)
        if publication_date is None:
            if gscholar_year is not None and 'n' not in gscholar_year.lower():
                publication_date = gscholar_year + '-01-01'
            elif semantic_year is not None and 'n' not in semantic_year.lower():
                publication_date = semantic_year + '-01-01'

        daily_citation_count = None if citation_count is None or publication_date is None else citation_count / max(1,utils.days_between(publication_date))

        return citation_count, daily_citation_count


    def citation_counts(self, titles, semantic_only=True):

        citation_counts = {}
        daily_citation_counts = {}

        for title in tqdm(titles):
            citation_count, daily_citation_count = self.citation_count(title, semantic_only=semantic_only)
            citation_counts[title] = citation_count
            daily_citation_counts[title] = daily_citation_count

        return {'citation counts': citation_counts, 'daily citation counts': daily_citation_counts}


    def bulldozer(self, titles, queue=None, keywords=None):
        
        if queue is None: # queue refers to titles NOT to include (already seen/known)
            queue = titles[:]
        queue = [self.process_title(title) for title in queue]       
        
        paper_info = {}


        for title in tqdm(titles):
            paper = self.find_on_semantic_scholar(title)
            if paper is None or not self._check_title_match(title, paper['title']):
                print('No result ! <- ', title)
                continue
            citations = utils.try_multiple_times(self.SCH.get_paper_citations, paper['paperId'])
            references = utils.try_multiple_times(self.SCH.get_paper_references, paper['paperId'])
            for key, pubs in zip(['citingPaper','citedPaper'],[citations, references]):
                pubs_iter = iter(pubs)
                pubs_list = []
                while len(pubs_list) == 0 or pubs_list[-1] is not None:
                    pubs_list.append(utils.try_multiple_times(next, pubs_iter, None))
                del pubs_list[-1]
                pubs_list = [pub[key] for pub in pubs_list]
                for pub in pubs_list:
                    if 'citationCount' not in pub:
                        print("'citationCount' not in pub")
                    if 'publicationDate' not in pub:
                        print("'publicationDate' not in pub")
                    title_processed = self.process_title(pub['title'])
                    if title_processed not in queue and title_processed not in paper_info:
                        paper_info[title_processed] = {
                            'title': pub['title'], 
                            'abstract': pub.get('abstract',''),
                        }

        selected_titles = self._multi_filter(paper_info, keywords)

        return selected_titles



    def _multi_filter(self, entries, keywords, entries_keys=None):
    
        titles_selected = []
        for title, entry in entries.items():
            if isinstance(entry, dict):
                args = tuple(entry.values()) if entries_keys is None else tuple(entry[key] for key in entries_keys)
            else:
                args = tuple(entry)
            if self._filter_entry(*args, keywords=keywords):
                titles_selected.append(title)
        
        return titles_selected
    


    def filter(self, titles, keywords=None, manual=True, sources=['arxiv','semanticscholar']):
        
        titles_filtered = []
        papers = {} if isinstance(titles, list) else titles
        if len(papers) == 0:
            print('Getting abstracts')
            for title in tqdm(titles):
                paper_dict = self.paperdict(title, sources=sources)
                if paper_dict is not None:
                    papers[title] = {
                        'title requested': title,
                        'title found': unidecode(
                            (lambda c: c if c is not None else '')(paper_dict.get('title', ''))),
                        'abstract': unidecode((lambda c: c if c is not None else '')(paper_dict.get('abstract', ''))),
                    }
                else:
                    papers[title] = {'title': title}

        titles_filtered.extend(self._multi_filter(entries=papers, keywords=keywords))

        # Manual purge
        titles_filtered_manual = []
        for title in tqdm(titles_filtered):
            if not manual:
                titles_filtered_manual.append(title)
            else:
                print(' ')
                for key, value in papers[title].items():
                    print(key, ' : ', value)
                print(' ')
                if utils.yes_or_no('Add this title? '):
                    titles_filtered_manual.append(title)

        titles_filtered_manual = self.purge_duplicates(titles_filtered_manual)
        return titles_filtered_manual

    def _filter_entry(self, *args, keywords=()):

        args = [arg for arg in args if arg is not None]

        if keywords is None:
            return True
        
        elif isinstance(keywords, tuple):
            result = True
            for keyword in keywords:
                result = result and self._filter_entry(*args, keywords=keyword)
                if not result:
                    break
            return result
        
        elif isinstance(keywords, list):
            result = False
            for keyword in keywords:
                result = result or self._filter_entry(*args, keywords=keyword)
                if result:
                    break
            return result
        
        elif isinstance(keywords, str) and keywords[0] == '~':
            keyword = keywords[1:]
            return not self._filter_entry(*args, keywords=keyword)
        
        elif isinstance(keywords, str):
            result = False
            keyword = keywords
            for arg in args:
                result = result or keyword.lower() in arg.lower()
                if result:
                    break
            return result
        
        else:
            return self._filter_entry(*args, str(keywords))
        

    def parse_arxiv(self, start=None, end=None, keywords=None):
        end = date.today() - timedelta(1) if end is None else datetime.strptime(end, '%Y-%m-%d').date()
        start = end if start is None else datetime.strptime(start, '%Y-%m-%d').date()

        base_url = "http://export.arxiv.org/api/query?"
        start = start.strftime("%Y%m%d") + "0000"
        end = end.strftime("%Y%m%d") + "2359"

        cats_substr = ""
        for c in self.arxiv_cats:
            cats_substr += f"cat:{c}+OR+"
        cats_substr = cats_substr[:-4]

        query = f"search_query=%28{cats_substr}%29+AND+lastUpdatedDate:[{start}+TO+{end}]&start=0&max_results={self.arxiv_max_results}"
        response = urllib.request.urlopen(base_url + query).read()
        feed = feedparser.parse(response)
        assert len(feed.entries) < self.arxiv_max_results
        feed_entries = sorted(feed.entries, key=(lambda d: d['updated']))

        titles_selected = []

        for entry in feed_entries:
            if self._filter_entry(entry.title, entry.summary, keywords=keywords):
                titles_selected.append(entry.title.replace("\n", "").replace("  ", " "))
                
        return titles_selected

    def _check_title_match(self, title1, title2):
        return  self._shorten_title_name(title1) ==  self._shorten_title_name(title2)

    def bibtexs_to_paperdict_list(self, bib_text):
        return bibtexparser.loads(bib_text).entries

    def bibtex_to_paperdict(self, bib_text):
        paperdict_list = self.bibtexs_to_paperdict_list(bib_text)
        assert len(paperdict_list) == 1
        return paperdict_list[0]

    def paperdict_list_to_bibtexs(self, paperdict_list):
        db = BibDatabase()
        db.entries = paperdict_list
        writer = BibTexWriter()
        return writer.write(db)

    def paperdict_to_bibtex(self, paperdict):
        return self.paperdict_list_to_bibtexs([paperdict])

    def _format_abstract(self, abstract):
        return abstract.replace('\n',' ').replace('  ',' ')

    def _paperdict_from_arxiv_result(self, result):
        pdf_url = result.pdf_url
        bibtex_link = result.entry_id.replace('abs', 'bibtex')
        abstract = result.summary
        bibtex = urllib.request.urlopen(bibtex_link).read().decode('utf-8')
        paperdict = self.bibtex_to_paperdict(bibtex)
        paperdict['abstract'] = self._format_abstract(abstract)
        paperdict['url'] = pdf_url
        return paperdict

    def search_google(self, query):
        try:
            return next(url for url in google_search_module(query))
        except:
            print("Error in Google Search without proxy - trying with proxy")
            if self.scraper_api_key is not None:
                proxy =  f"http://scraperapi:{self.scraper_api_key}@proxy-server.scraperapi.com:8001"
                return next(url for url in google_search_module(query, proxy=proxy, ssl_verify=False, timeout=120))
            else:
                raise "No proxy available! Error!"

    def search_arxiv(self, title):

        arxiv_search = arxiv.Search(
            query=f'"{title}"',
            max_results=1,
            sort_by=arxiv.SortCriterion.SubmittedDate
        )

        for result in arxiv.Client().results(arxiv_search):
            if self._check_title_match(title, result.title):
                return result
        try:
            arxiv_search = arxiv.Search(
                id_list=[self.search_google(title + ' site:arxiv.org').split('/')[-1]],
                max_results=1,
                sort_by=arxiv.SortCriterion.SubmittedDate
            )
            for result in arxiv.Client().results(arxiv_search):
                return result
        except Exception:
            traceback.print_exc()
            print('Google search crashed')
            return None
        return None

    def _paperdict_arxiv(self, title):
        result = self.search_arxiv(title)
        return self._paperdict_from_arxiv_result(result) if result is not None else None


    def _paperdict_googlescholar(self, title):
        pub = scholarly.search_single_pub(title)
        if pub is not None:
            pub = scholarly.fill(pub)
            bibtex = scholarly.bibtex(pub)
            bibtex = bibtex.replace('pub_year', 'year')
            paperdict = self.bibtex_to_paperdict(bibtex)
            if "eprint_url" in pub:
                paperdict['url'] = pub["eprint_url"]
            return paperdict
        else:
            return None

    def _paperdict_semanticscholar(self, title):
        if not isinstance(title, str):
            pub = title
        else:
            pub = self.find_on_semantic_scholar(title)
        fields = self._get_fields_from_pub(pub, fields='citationStyles,openAccessPdf,abstract')
        bibtex = fields['citationStyles']['bibtex'].strip('\n ')
        paperdict = self.bibtex_to_paperdict(bibtex)
        abstract = fields['abstract']
        if abstract is not None:
            paperdict['abstract'] = self._format_abstract(abstract)
        if fields['openAccessPdf'] is not None:
            paperdict['url'] = fields['openAccessPdf']['url']
        return paperdict
    
    def load_existing_bibs(self):
        result = {}
        for bib_file_name in glob.glob(os.path.join(project, '**', '*.bib'), recursive = True):
            with open(bib_file_name, 'r') as bib_file:
                for paperdict in self.bibtexs_to_paperdict_list(bib_file.read()):
                    title = paperdict['title'].lower().strip()
                    result[title] = dict(**paperdict)
        return result
    
    def _paperdict_own(self, title):
        title = title.lower().strip()
        existing_bibs = {}
        if os.path.exists(self.folder):
            existing_bibs = self.load_existing_bibs()
        return existing_bibs[title] if title in existing_bibs else None

    def _change_id(self, paperdict):
        if 'author' not in paperdict or 'year' not in paperdict or 'title' not in paperdict:
            print("Weird paperdict, some vital fields (author, year and/or title) are missing. Imputing what's missing with NA. Please check the original paperdict: ", paperdict)
            for key in ['author','year','title']:
                if key not in paperdict:
                    paperdict[key] = 'NA'
        author_short =  self._shorten_author_name(paperdict['author'].split(',')[0]).lower() if ',' in paperdict['author'] else  self._shorten_author_name(paperdict['author'].split(' and ')[0].split(' ')[ -1]).lower()  # _shorten_author_name(paperdict['author'].split(' and ')[0].strip().split(' ')[-1]).lower()
        year = paperdict['year']
        title_short =  self._shorten_title_name(paperdict['title'])
        filename = f'{author_short}{year}{title_short}'
        paperdict['ID'] = filename
        return paperdict
    


    def paperdict(self, title, check_title=True, change_id=True, sources=['arxiv','own','googlescholar','semanticscholar']):
        paperdict_methods_dict = {
            'own': self._paperdict_own,
            'arxiv': self._paperdict_arxiv,
            'googlescholar': self._paperdict_googlescholar,
            'semanticscholar': self._paperdict_semanticscholar
        }
        assert isinstance(title, str)
        if isinstance(sources, str):
            sources = [sources]
        paperdict = None
        for source in sources:
            print(f"Trying title '{title}' with '{source}'")
            try:
                paperdict = paperdict_methods_dict[source](title)
            except Exception:
                traceback.print_exc()
                print(f"Bug when trying title '{title}' with '{source}'")
                paperdict = None
            if paperdict is not None and check_title and not self._check_title_match(title, paperdict['title']):
                print(f"Titles do not correspond :\n{title}\n{paperdict['title']}")
                paperdict = None
            if paperdict is not None:
                print('Found!')
                if change_id:
                    paperdict = self._change_id(paperdict)
                break
            else:
                print(f"Got None when trying title '{title}' with '{source}'")
        if paperdict is None:
            print(f"WARNING : ALWAYS GOT NONE FOR '{title}'")
        return paperdict

    def bibtex(self, title, **kwargs):
        return self.paperdict_to_bibtex(self.paperdict(title, **kwargs))

    def paperdicts(self, titles, sort_by_year=True, **kwargs):
        result = []
        for title in tqdm(titles):
            paperdict = self.paperdict(title, **kwargs)
            if paperdict is not None:
                result.append(paperdict)
        if sort_by_year:
            result = sorted(result, key=(lambda d: d.get('year','9999')))
        return result
    
    def bibtexs(self, titles, **kwargs):
        return self.paperdict_list_to_bibtexs(self.paperdicts(titles, **kwargs))


    def _shorten_author_name(self, author):
        return ''.join([c for c in author if c.isalpha()])

    def _shorten_title_name(self, title):
        shortened = ''
        for c in title.lower():
            if c.isalpha():
                shortened = shortened + c
            else:
                shortened = shortened + ' '
        shortened = [s[0] for s in shortened.split(' ') if len(s) > 0]
        return ''.join(shortened)

    def download(self, titles, folder, sources=['arxiv','googlescholar','semanticscholar']):
        folder = os.path.expanduser(folder)
        if not os.path.exists(folder):
            raise 'Incorrect folder'
       
        paperdicts = self.paperdicts(titles, sources=sources)
        for bib_dict in paperdicts:
            url = bib_dict['url'] if 'url' in bib_dict else None
            filename = bib_dict['ID']
            if url is not None:
                try:
                    urllib.request.urlretrieve(url, os.path.join(folder, filename + ".pdf"))
                    print(f"Downloaded file {filename}.pdf from {url}")
                except:
                    print(f"**Warning :** the URL specified for {filename} is not downloadable")
            else:
                print(f"**Warning :** no URL specified for {filename}")

        return paperdicts