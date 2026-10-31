import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Toaster} from 'sonner';
import SuppliedBooksPage from './SuppliedBooksPage';
import {BookRuntimeContext,type ShelfRuntime} from './VellumRuntime';
import type {ShelfBookItem} from './lib/book-types';
import './bookshelf.css';

type CanonicalBook={id:string;title:string;authors:string[];cover_url:string;cover_aspect?:number;cover_palette?:{spineColor:string;accentColor:string;inkColor:string};content_chars?:number;reader_progress?:number;date_added?:string};
type Props={books:CanonicalBook[];loading:boolean;rightsVersion:string;openBookId?:string;onRefresh:()=>Promise<unknown>;onTheme:(theme:string)=>void;onClose:()=>void;onSelect:(id:string)=>void;onProgress:(id:string,value:number)=>Promise<unknown>;onRemove:ShelfRuntime['removeBook'];onImportFile:ShelfRuntime['importFile'];onImportUrl:ShelfRuntime['importUrl']};

export function toShelfBook(book:CanonicalBook):ShelfBookItem {
  return {id:book.id,title:book.title,author:book.authors.join(', ') || 'Unknown',source:'upload',gutenbergId:null,hasCover:!!book.cover_url,coverUrl:book.cover_url||null,coverAspect:book.cover_aspect||null,spineColor:book.cover_palette?.spineColor||'',accentColor:book.cover_palette?.accentColor||'',inkColor:book.cover_palette?.inkColor||'',contentChars:book.content_chars||0,progress:book.reader_progress||0,dateAdded:book.date_added||''};
}
export function VellumBookshelf(props:Props) {
  const latest=useRef(props);latest.current=props;
  const [theme,setTheme]=useState(()=>document.documentElement.dataset.theme==='light'?'light':'dark');
  useEffect(()=>{const sync=()=>setTheme(document.documentElement.dataset.theme==='light'?'light':'dark');const observer=new MutationObserver(sync);observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});sync();return()=>observer.disconnect();},[]);
  const books=useMemo(()=>props.books.map(toShelfBook),[props.books]);
  const refresh=useCallback(()=>latest.current.onRefresh(),[]);
  const changeTheme=useCallback((value:string)=>latest.current.onTheme(value),[]);
  const saveProgress=useCallback((id:string,value:number)=>latest.current.onProgress(id,value),[]);
  const importFile=useCallback<ShelfRuntime['importFile']>((...args)=>latest.current.onImportFile(...args),[]);
  const importUrl=useCallback<ShelfRuntime['importUrl']>((...args)=>latest.current.onImportUrl(...args),[]);
  const onSelect=useCallback((id:string)=>latest.current.onSelect(id),[]);
  const onClose=useCallback(()=>latest.current.onClose(),[]);
  const removeBook=useCallback((id:string)=>latest.current.onRemove(id),[]);
  const runtime:ShelfRuntime={onSelect,onClose,books,loading:props.loading&&books.length===0,theme,rightsVersion:props.rightsVersion,openBookId:props.openBookId,refresh,setTheme:changeTheme,saveProgress,removeBook,importFile,importUrl,
    loadBook:async(book,signal)=>{const data=await window.VellumApi.books.readerText(book.id,signal);return {...book,content:data.content};},
    importText:(title,author,text,consent)=>importFile(new File([text],title+'.txt',{type:'text/plain'}),title,author,null,consent),
  };
  return <BookRuntimeContext.Provider value={runtime}><div className="bk-reference bk-reference-scene"><SuppliedBooksPage/><Toaster position="bottom-center" theme={theme==='dark'?'dark':'light'} richColors={false}/></div></BookRuntimeContext.Provider>;
}
window.VellumBookshelf={mount(host:HTMLElement,props:Props){const root=createRoot(host);const render=(next:Props)=>root.render(<VellumBookshelf {...next}/>);render(props);return{update:render,unmount:()=>root.unmount()};}};
window.dispatchEvent(new Event('vellum:bookshelf-ready'));
