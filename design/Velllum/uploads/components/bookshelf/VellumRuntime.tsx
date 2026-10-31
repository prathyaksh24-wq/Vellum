import {createContext, useContext} from 'react';
import type {FullBook, ShelfBookItem} from './lib/book-types';

export type ImportConsent = {scanApproved:boolean; rightsAttestationVersion:string; localOnly:boolean};
export type ShelfRuntime = {
  books:ShelfBookItem[]; loading:boolean; theme:string; rightsVersion:string; openBookId?:string;
  onSelect:(id:string)=>void; onClose:()=>void;
  refresh:()=>Promise<unknown>; setTheme:(theme:string)=>void;
  loadBook:(book:ShelfBookItem,signal?:AbortSignal)=>Promise<FullBook>;
  saveProgress:(id:string,value:number)=>Promise<unknown>;
  removeBook:(id:string)=>Promise<void>;
  importFile:(file:File,title:string,author:string,cover:File|null,consent:ImportConsent)=>Promise<{title:string;alreadyPresent?:boolean}>;
  importText:(title:string,author:string,text:string,consent:ImportConsent)=>Promise<{title:string}>;
  importUrl:(url:string,consent:ImportConsent)=>Promise<{title:string}>;
};
export const BookRuntimeContext = createContext<ShelfRuntime|null>(null);
export function useBookRuntime() {
  const value=useContext(BookRuntimeContext);
  if(!value) throw new Error('The Books runtime is unavailable.');
  return value;
}
export function useTheme() {
  const runtime=useBookRuntime();
  return {resolvedTheme:runtime.theme,setTheme:runtime.setTheme};
}
