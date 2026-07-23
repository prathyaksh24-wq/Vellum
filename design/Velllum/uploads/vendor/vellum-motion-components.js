/*! border-beam 1.3.0 and thinking-orbs 0.1.1, Copyright 2026 Jakub Antalik, MIT License. Adapted for the Vellum standalone workspace. */
(()=>{var E=window.React,pr=E.Children,br=E.Fragment,dr=E.cloneElement,fr=E.createElement,Be=E.forwardRef,mr=E.isValidElement,he=E.useCallback,I=E.useEffect,De=E.useId,gr=E.useLayoutEffect,xe=E.useMemo,le=E.useRef,A=E.useState;var Fe={sm:{borderRadius:32,borderWidth:1,width:70,height:36},md:{borderRadius:16,borderWidth:1},line:{borderRadius:16,borderWidth:1},"pulse-outside":{borderRadius:16,borderWidth:1},"pulse-inner":{borderRadius:16,borderWidth:1}},be={sm:{dark:{strokeOpacity:.46,innerOpacity:.24,bloomOpacity:.38,innerShadow:"rgba(255, 255, 255, 0.3)",saturation:1.2},light:{strokeOpacity:.12,innerOpacity:.3,bloomOpacity:.16,innerShadow:"rgba(0, 0, 0, 0.14)",saturation:1.8}},md:{dark:{strokeOpacity:.26,innerOpacity:.42,bloomOpacity:.24,innerShadow:"rgba(255, 255, 255, 0.27)",saturation:1.2},light:{strokeOpacity:.12,innerOpacity:.26,bloomOpacity:.34,innerShadow:"rgba(0, 0, 0, 0.14)",saturation:1.5}},line:{dark:{strokeOpacity:1.14,innerOpacity:.7,bloomOpacity:.8,innerShadow:"rgba(255, 255, 255, 0.1)",saturation:1.2},light:{strokeOpacity:.16,innerOpacity:.32,bloomOpacity:.3,innerShadow:"rgba(0, 0, 0, 0.14)",saturation:1.95}},"pulse-outside":{dark:{strokeOpacity:.94,innerOpacity:.34,bloomOpacity:.3,innerShadow:"transparent",saturation:1.2,brightness:1.9,hairlineOpacity:0},light:{strokeOpacity:1.96,innerOpacity:1.04,bloomOpacity:.42,innerShadow:"transparent",saturation:.6,brightness:1.7,hairlineOpacity:0}},"pulse-inner":{dark:{strokeOpacity:1.54,innerOpacity:.44,bloomOpacity:.66,innerShadow:"transparent",saturation:1.2,brightness:.75},light:{strokeOpacity:.32,innerOpacity:.4,bloomOpacity:.8,innerShadow:"transparent",saturation:.75,brightness:1.3}}},hr={dark:{...be.md.dark},light:{...be.md.light}},K={colorful:{border:[{color:"rgb(255, 50, 100)",pos:"33% -7.4%",size:"70px 40px"},{color:"rgb(40, 140, 255)",pos:"12% -5%",size:"60px 35px"},{color:"rgb(50, 200, 80)",pos:"2.1% 68.3%",size:"40px 70px"},{color:"rgb(30, 185, 170)",pos:"2.1% 68.3%",size:"20px 35px"},{color:"rgb(100, 70, 255)",pos:"74.4% 100%",size:"180px 32px"},{color:"rgb(40, 140, 255)",pos:"55% 100%",size:"85px 26px"},{color:"rgb(255, 120, 40)",pos:"93.9% 0%",size:"74px 32px"},{color:"rgb(240, 50, 180)",pos:"100% 27.1%",size:"26px 42px"},{color:"rgb(180, 40, 240)",pos:"100% 27.1%",size:"52px 48px"}],spike:{primary:"rgb(255, 60, 80)",secondary:"rgba(40, 190, 180, 0.98)"},spikeLt:{primary:"rgb(200, 30, 60)",secondary:"rgb(20, 150, 140)"}},mono:{border:[{color:"rgb(180, 180, 180)",pos:"33% -7.4%",size:"70px 40px"},{color:"rgb(140, 140, 140)",pos:"12% -5%",size:"60px 35px"},{color:"rgb(160, 160, 160)",pos:"2.1% 68.3%",size:"40px 70px"},{color:"rgb(130, 130, 130)",pos:"2.1% 68.3%",size:"20px 35px"},{color:"rgb(170, 170, 170)",pos:"74.4% 100%",size:"180px 32px"},{color:"rgb(150, 150, 150)",pos:"55% 100%",size:"85px 26px"},{color:"rgb(190, 190, 190)",pos:"93.9% 0%",size:"74px 32px"},{color:"rgb(145, 145, 145)",pos:"100% 27.1%",size:"26px 42px"},{color:"rgb(165, 165, 165)",pos:"100% 27.1%",size:"52px 48px"}],spike:{primary:"rgb(200, 200, 200)",secondary:"rgb(170, 170, 170)"},spikeLt:{primary:"rgb(80, 80, 80)",secondary:"rgb(120, 120, 120)"}},ocean:{border:[{color:"rgb(100, 80, 220)",pos:"33% -7.4%",size:"70px 40px"},{color:"rgb(60, 120, 255)",pos:"12% -5%",size:"60px 35px"},{color:"rgb(80, 100, 200)",pos:"2.1% 68.3%",size:"40px 70px"},{color:"rgb(50, 140, 220)",pos:"2.1% 68.3%",size:"20px 35px"},{color:"rgb(120, 80, 255)",pos:"74.4% 100%",size:"180px 32px"},{color:"rgb(70, 130, 255)",pos:"55% 100%",size:"85px 26px"},{color:"rgb(140, 100, 240)",pos:"93.9% 0%",size:"74px 32px"},{color:"rgb(90, 110, 230)",pos:"100% 27.1%",size:"26px 42px"},{color:"rgb(130, 70, 255)",pos:"100% 27.1%",size:"52px 48px"}],spike:{primary:"rgb(100, 120, 255)",secondary:"rgba(130, 100, 220, 0.98)"},spikeLt:{primary:"rgb(60, 60, 180)",secondary:"rgb(80, 100, 200)"}},sunset:{border:[{color:"rgb(255, 80, 50)",pos:"33% -7.4%",size:"70px 40px"},{color:"rgb(255, 160, 40)",pos:"12% -5%",size:"60px 35px"},{color:"rgb(255, 120, 60)",pos:"2.1% 68.3%",size:"40px 70px"},{color:"rgb(255, 200, 50)",pos:"2.1% 68.3%",size:"20px 35px"},{color:"rgb(255, 100, 80)",pos:"74.4% 100%",size:"180px 32px"},{color:"rgb(255, 180, 60)",pos:"55% 100%",size:"85px 26px"},{color:"rgb(255, 60, 60)",pos:"93.9% 0%",size:"74px 32px"},{color:"rgb(255, 140, 50)",pos:"100% 27.1%",size:"26px 42px"},{color:"rgb(255, 90, 70)",pos:"100% 27.1%",size:"52px 48px"}],spike:{primary:"rgb(255, 140, 80)",secondary:"rgba(255, 100, 60, 0.98)"},spikeLt:{primary:"rgb(200, 80, 40)",secondary:"rgb(220, 120, 30)"}}},Ie={colorful:{border:[{color:"rgb(50, 200, 80)",pos:"2% 68%",size:"9px 18px"},{color:"rgb(30, 185, 170)",pos:"2% 68%",size:"4px 8px"},{color:"rgb(255, 120, 40)",pos:"72% -3%",size:"59px 9px"},{color:"rgb(100, 70, 255)",pos:"74% 100%",size:"42px 7px"},{color:"rgb(240, 50, 180)",pos:"100% 27%",size:"10px 17px"},{color:"rgb(180, 40, 240)",pos:"100% 27%",size:"10px 18px"},{color:"rgb(40, 140, 255)",pos:"100% 27%",size:"5px 10px"},{color:"rgb(255, 50, 100)",pos:"100% 27%",size:"11px 12px"}],inner:[{color:"rgba(50, 200, 80, 0.5)",pos:"2% 68%",size:"9px 18px"},{color:"rgba(30, 185, 170, 0.45)",pos:"2% 68%",size:"4px 8px"},{color:"rgba(255, 120, 40, 0.35)",pos:"72% -3%",size:"59px 9px"},{color:"rgba(100, 70, 255, 0.35)",pos:"74% 100%",size:"42px 7px"},{color:"rgba(240, 50, 180, 0.3)",pos:"100% 27%",size:"10px 17px"},{color:"rgba(180, 40, 240, 0.4)",pos:"100% 27%",size:"10px 18px"},{color:"rgba(40, 140, 255, 0.3)",pos:"100% 27%",size:"5px 10px"},{color:"rgba(255, 50, 100, 0.3)",pos:"100% 27%",size:"11px 12px"}]},mono:{border:[{color:"rgb(160, 160, 160)",pos:"2% 68%",size:"9px 18px"},{color:"rgb(140, 140, 140)",pos:"2% 68%",size:"4px 8px"},{color:"rgb(180, 180, 180)",pos:"72% -3%",size:"59px 9px"},{color:"rgb(150, 150, 150)",pos:"74% 100%",size:"42px 7px"},{color:"rgb(170, 170, 170)",pos:"100% 27%",size:"10px 17px"},{color:"rgb(155, 155, 155)",pos:"100% 27%",size:"10px 18px"},{color:"rgb(145, 145, 145)",pos:"100% 27%",size:"5px 10px"},{color:"rgb(165, 165, 165)",pos:"100% 27%",size:"11px 12px"}],inner:[{color:"rgba(160, 160, 160, 0.25)",pos:"2% 68%",size:"9px 18px"},{color:"rgba(140, 140, 140, 0.22)",pos:"2% 68%",size:"4px 8px"},{color:"rgba(180, 180, 180, 0.17)",pos:"72% -3%",size:"59px 9px"},{color:"rgba(150, 150, 150, 0.17)",pos:"74% 100%",size:"42px 7px"},{color:"rgba(170, 170, 170, 0.15)",pos:"100% 27%",size:"10px 17px"},{color:"rgba(155, 155, 155, 0.20)",pos:"100% 27%",size:"10px 18px"},{color:"rgba(145, 145, 145, 0.15)",pos:"100% 27%",size:"5px 10px"},{color:"rgba(165, 165, 165, 0.15)",pos:"100% 27%",size:"11px 12px"}]},ocean:{border:[{color:"rgb(60, 140, 200)",pos:"2% 68%",size:"9px 18px"},{color:"rgb(50, 120, 180)",pos:"2% 68%",size:"4px 8px"},{color:"rgb(100, 80, 220)",pos:"72% -3%",size:"59px 9px"},{color:"rgb(80, 100, 255)",pos:"74% 100%",size:"42px 7px"},{color:"rgb(120, 70, 240)",pos:"100% 27%",size:"10px 17px"},{color:"rgb(90, 80, 220)",pos:"100% 27%",size:"10px 18px"},{color:"rgb(70, 110, 255)",pos:"100% 27%",size:"5px 10px"},{color:"rgb(110, 90, 230)",pos:"100% 27%",size:"11px 12px"}],inner:[{color:"rgba(60, 140, 200, 0.5)",pos:"2% 68%",size:"9px 18px"},{color:"rgba(50, 120, 180, 0.45)",pos:"2% 68%",size:"4px 8px"},{color:"rgba(100, 80, 220, 0.35)",pos:"72% -3%",size:"59px 9px"},{color:"rgba(80, 100, 255, 0.35)",pos:"74% 100%",size:"42px 7px"},{color:"rgba(120, 70, 240, 0.3)",pos:"100% 27%",size:"10px 17px"},{color:"rgba(90, 80, 220, 0.4)",pos:"100% 27%",size:"10px 18px"},{color:"rgba(70, 110, 255, 0.3)",pos:"100% 27%",size:"5px 10px"},{color:"rgba(110, 90, 230, 0.3)",pos:"100% 27%",size:"11px 12px"}]},sunset:{border:[{color:"rgb(255, 180, 50)",pos:"2% 68%",size:"9px 18px"},{color:"rgb(255, 150, 40)",pos:"2% 68%",size:"4px 8px"},{color:"rgb(255, 80, 60)",pos:"72% -3%",size:"59px 9px"},{color:"rgb(255, 100, 80)",pos:"74% 100%",size:"42px 7px"},{color:"rgb(255, 60, 80)",pos:"100% 27%",size:"10px 17px"},{color:"rgb(255, 120, 60)",pos:"100% 27%",size:"10px 18px"},{color:"rgb(255, 200, 50)",pos:"100% 27%",size:"5px 10px"},{color:"rgb(255, 90, 70)",pos:"100% 27%",size:"11px 12px"}],inner:[{color:"rgba(255, 180, 50, 0.5)",pos:"2% 68%",size:"9px 18px"},{color:"rgba(255, 150, 40, 0.45)",pos:"2% 68%",size:"4px 8px"},{color:"rgba(255, 80, 60, 0.35)",pos:"72% -3%",size:"59px 9px"},{color:"rgba(255, 100, 80, 0.35)",pos:"74% 100%",size:"42px 7px"},{color:"rgba(255, 60, 80, 0.3)",pos:"100% 27%",size:"10px 17px"},{color:"rgba(255, 120, 60, 0.4)",pos:"100% 27%",size:"10px 18px"},{color:"rgba(255, 200, 50, 0.3)",pos:"100% 27%",size:"5px 10px"},{color:"rgba(255, 90, 70, 0.3)",pos:"100% 27%",size:"11px 12px"}]}};function xt(a){return Ie[a].border.map(t=>`radial-gradient(ellipse ${t.size} at ${t.pos}, ${t.color}, transparent)`).join(`,
    `)}function $t(a){return Ie[a].inner.map(t=>`radial-gradient(ellipse ${t.size} at ${t.pos}, ${t.color}, transparent)`).join(`,
    `)}function yt(a){return K[a].border.map(t=>`radial-gradient(ellipse ${t.size} at ${t.pos}, ${t.color}, transparent)`).join(`,
    `)}function vt(a){let e=K[a],t=a==="mono"?.225:.45;return e.border.map(o=>{let r=o.color.replace("rgb(","rgba(").replace(")",`, ${t})`);return`radial-gradient(ellipse ${o.size.split(" ").map(s=>{let i=parseInt(s);return`${Math.round(i*.9)}px`}).join(" ")} at ${o.pos}, ${r}, transparent)`}).join(`,
    `)}function zt(a,e){let t=K[a];return e?t.spike:t.spikeLt}var kt={colorful:{dark:[{color:"rgb(255, 50, 100)",sizeW:36,sizeH:36,offsetX:0,offsetY:2},{color:"rgb(40, 180, 220)",sizeW:30,sizeH:32,offsetX:39,offsetY:0},{color:"rgb(50, 200, 80)",sizeW:33,sizeH:28,offsetX:-36,offsetY:2},{color:"rgb(180, 40, 240)",sizeW:29,sizeH:34,offsetX:-54,offsetY:0},{color:"rgb(255, 160, 30)",sizeW:27,sizeH:30,offsetX:51,offsetY:-1},{color:"rgb(100, 70, 255)",sizeW:36,sizeH:24,offsetX:21,offsetY:1},{color:"rgb(40, 140, 255)",sizeW:30,sizeH:22,offsetX:-21,offsetY:0},{color:"rgb(240, 50, 180)",sizeW:25,sizeH:28,offsetX:66,offsetY:1},{color:"rgb(30, 185, 170)",sizeW:23,sizeH:30,offsetX:-66,offsetY:-1}],light:[{color:"rgb(255, 50, 100)",sizeW:45,sizeH:36,offsetX:0,offsetY:2},{color:"rgb(40, 140, 255)",sizeW:35,sizeH:32,offsetX:65,offsetY:0},{color:"rgb(50, 200, 80)",sizeW:40,sizeH:28,offsetX:-60,offsetY:2},{color:"rgb(180, 40, 240)",sizeW:35,sizeH:34,offsetX:-90,offsetY:0},{color:"rgb(30, 185, 170)",sizeW:38,sizeH:30,offsetX:85,offsetY:-1},{color:"rgb(100, 70, 255)",sizeW:50,sizeH:24,offsetX:35,offsetY:1},{color:"rgb(40, 140, 255)",sizeW:40,sizeH:22,offsetX:-35,offsetY:0},{color:"rgb(255, 120, 40)",sizeW:35,sizeH:28,offsetX:110,offsetY:1},{color:"rgb(240, 50, 180)",sizeW:30,sizeH:30,offsetX:-110,offsetY:-1}]},mono:{dark:[{color:"rgb(200, 200, 200)",sizeW:36,sizeH:36,offsetX:0,offsetY:2},{color:"rgb(170, 170, 170)",sizeW:30,sizeH:32,offsetX:39,offsetY:0},{color:"rgb(155, 155, 155)",sizeW:33,sizeH:28,offsetX:-36,offsetY:2},{color:"rgb(185, 185, 185)",sizeW:29,sizeH:34,offsetX:-54,offsetY:0},{color:"rgb(165, 165, 165)",sizeW:27,sizeH:30,offsetX:51,offsetY:-1},{color:"rgb(180, 180, 180)",sizeW:36,sizeH:24,offsetX:21,offsetY:1},{color:"rgb(160, 160, 160)",sizeW:30,sizeH:22,offsetX:-21,offsetY:0},{color:"rgb(175, 175, 175)",sizeW:25,sizeH:28,offsetX:66,offsetY:1},{color:"rgb(190, 190, 190)",sizeW:23,sizeH:30,offsetX:-66,offsetY:-1}],light:[{color:"rgb(100, 100, 100)",sizeW:45,sizeH:36,offsetX:0,offsetY:2},{color:"rgb(80, 80, 80)",sizeW:35,sizeH:32,offsetX:65,offsetY:0},{color:"rgb(90, 90, 90)",sizeW:40,sizeH:28,offsetX:-60,offsetY:2},{color:"rgb(70, 70, 70)",sizeW:35,sizeH:34,offsetX:-90,offsetY:0},{color:"rgb(85, 85, 85)",sizeW:38,sizeH:30,offsetX:85,offsetY:-1},{color:"rgb(95, 95, 95)",sizeW:50,sizeH:24,offsetX:35,offsetY:1},{color:"rgb(75, 75, 75)",sizeW:40,sizeH:22,offsetX:-35,offsetY:0},{color:"rgb(105, 105, 105)",sizeW:35,sizeH:28,offsetX:110,offsetY:1},{color:"rgb(65, 65, 65)",sizeW:30,sizeH:30,offsetX:-110,offsetY:-1}]},ocean:{dark:[{color:"rgb(100, 80, 220)",sizeW:36,sizeH:36,offsetX:0,offsetY:2},{color:"rgb(60, 120, 255)",sizeW:30,sizeH:32,offsetX:39,offsetY:0},{color:"rgb(80, 100, 200)",sizeW:33,sizeH:28,offsetX:-36,offsetY:2},{color:"rgb(130, 70, 255)",sizeW:29,sizeH:34,offsetX:-54,offsetY:0},{color:"rgb(70, 130, 255)",sizeW:27,sizeH:30,offsetX:51,offsetY:-1},{color:"rgb(120, 80, 255)",sizeW:36,sizeH:24,offsetX:21,offsetY:1},{color:"rgb(90, 110, 230)",sizeW:30,sizeH:22,offsetX:-21,offsetY:0},{color:"rgb(110, 90, 240)",sizeW:25,sizeH:28,offsetX:66,offsetY:1},{color:"rgb(140, 100, 255)",sizeW:23,sizeH:30,offsetX:-66,offsetY:-1}],light:[{color:"rgb(80, 60, 200)",sizeW:45,sizeH:36,offsetX:0,offsetY:2},{color:"rgb(50, 100, 220)",sizeW:35,sizeH:32,offsetX:65,offsetY:0},{color:"rgb(70, 90, 190)",sizeW:40,sizeH:28,offsetX:-60,offsetY:2},{color:"rgb(110, 60, 220)",sizeW:35,sizeH:34,offsetX:-90,offsetY:0},{color:"rgb(60, 110, 230)",sizeW:38,sizeH:30,offsetX:85,offsetY:-1},{color:"rgb(100, 70, 240)",sizeW:50,sizeH:24,offsetX:35,offsetY:1},{color:"rgb(80, 100, 210)",sizeW:40,sizeH:22,offsetX:-35,offsetY:0},{color:"rgb(90, 80, 225)",sizeW:35,sizeH:28,offsetX:110,offsetY:1},{color:"rgb(120, 90, 245)",sizeW:30,sizeH:30,offsetX:-110,offsetY:-1}]},sunset:{dark:[{color:"rgb(255, 100, 60)",sizeW:36,sizeH:36,offsetX:0,offsetY:2},{color:"rgb(255, 180, 50)",sizeW:30,sizeH:32,offsetX:39,offsetY:0},{color:"rgb(255, 140, 70)",sizeW:33,sizeH:28,offsetX:-36,offsetY:2},{color:"rgb(255, 80, 80)",sizeW:29,sizeH:34,offsetX:-54,offsetY:0},{color:"rgb(255, 200, 60)",sizeW:27,sizeH:30,offsetX:51,offsetY:-1},{color:"rgb(255, 120, 50)",sizeW:36,sizeH:24,offsetX:21,offsetY:1},{color:"rgb(255, 160, 80)",sizeW:30,sizeH:22,offsetX:-21,offsetY:0},{color:"rgb(255, 90, 60)",sizeW:25,sizeH:28,offsetX:66,offsetY:1},{color:"rgb(255, 70, 70)",sizeW:23,sizeH:30,offsetX:-66,offsetY:-1}],light:[{color:"rgb(220, 80, 40)",sizeW:45,sizeH:36,offsetX:0,offsetY:2},{color:"rgb(230, 150, 30)",sizeW:35,sizeH:32,offsetX:65,offsetY:0},{color:"rgb(210, 110, 50)",sizeW:40,sizeH:28,offsetX:-60,offsetY:2},{color:"rgb(200, 60, 60)",sizeW:35,sizeH:34,offsetX:-90,offsetY:0},{color:"rgb(220, 170, 40)",sizeW:38,sizeH:30,offsetX:85,offsetY:-1},{color:"rgb(210, 100, 30)",sizeW:50,sizeH:24,offsetX:35,offsetY:1},{color:"rgb(230, 130, 60)",sizeW:40,sizeH:22,offsetX:-35,offsetY:0},{color:"rgb(190, 70, 50)",sizeW:35,sizeH:28,offsetX:110,offsetY:1},{color:"rgb(180, 50, 50)",sizeW:30,sizeH:30,offsetX:-110,offsetY:-1}]}};function wt(a,e,t){return kt[a][e?"dark":"light"].map(r=>{let n=r.offsetX===0?"":r.offsetX>0?` + ${r.offsetX}px`:` - ${Math.abs(r.offsetX)}px`,s=r.offsetY===0?"":r.offsetY>0?` + ${r.offsetY}px`:` - ${Math.abs(r.offsetY)}px`;return`radial-gradient(ellipse calc(${r.sizeW}px * var(--beam-w-${t})) calc(${r.sizeH}px * var(--beam-h-${t})) at calc(var(--beam-x-${t}) * 100%${n}) calc(100%${s}), ${r.color}, transparent)`}).join(`,
       `)}var Mt={colorful:[{color:"rgba(255, 50, 100, 0.48)",sizeW:33,sizeH:30,offsetX:0,offsetY:0},{color:"rgba(40, 180, 220, 0.42)",sizeW:24,sizeH:26,offsetX:39,offsetY:-3},{color:"rgba(50, 200, 80, 0.48)",sizeW:27,sizeH:24,offsetX:-36,offsetY:0},{color:"rgba(180, 40, 240, 0.42)",sizeW:23,sizeH:28,offsetX:-54,offsetY:-2},{color:"rgba(255, 160, 30, 0.50)",sizeW:24,sizeH:24,offsetX:51,offsetY:-1},{color:"rgba(100, 70, 255, 0.45)",sizeW:30,sizeH:20,offsetX:21,offsetY:0},{color:"rgba(40, 140, 255, 0.40)",sizeW:25,sizeH:18,offsetX:-21,offsetY:-2},{color:"rgba(240, 50, 180, 0.45)",sizeW:21,sizeH:24,offsetX:66,offsetY:0},{color:"rgba(30, 185, 170, 0.52)",sizeW:18,sizeH:26,offsetX:-66,offsetY:-1}],mono:[{color:"rgba(200, 200, 200, 0.48)",sizeW:33,sizeH:30,offsetX:0,offsetY:0},{color:"rgba(170, 170, 170, 0.42)",sizeW:24,sizeH:26,offsetX:39,offsetY:-3},{color:"rgba(155, 155, 155, 0.48)",sizeW:27,sizeH:24,offsetX:-36,offsetY:0},{color:"rgba(185, 185, 185, 0.42)",sizeW:23,sizeH:28,offsetX:-54,offsetY:-2},{color:"rgba(165, 165, 165, 0.50)",sizeW:24,sizeH:24,offsetX:51,offsetY:-1},{color:"rgba(180, 180, 180, 0.45)",sizeW:30,sizeH:20,offsetX:21,offsetY:0},{color:"rgba(160, 160, 160, 0.40)",sizeW:25,sizeH:18,offsetX:-21,offsetY:-2},{color:"rgba(175, 175, 175, 0.45)",sizeW:21,sizeH:24,offsetX:66,offsetY:0},{color:"rgba(190, 190, 190, 0.52)",sizeW:18,sizeH:26,offsetX:-66,offsetY:-1}],ocean:[{color:"rgba(100, 80, 220, 0.48)",sizeW:33,sizeH:30,offsetX:0,offsetY:0},{color:"rgba(60, 120, 255, 0.42)",sizeW:24,sizeH:26,offsetX:39,offsetY:-3},{color:"rgba(80, 100, 200, 0.48)",sizeW:27,sizeH:24,offsetX:-36,offsetY:0},{color:"rgba(130, 70, 255, 0.42)",sizeW:23,sizeH:28,offsetX:-54,offsetY:-2},{color:"rgba(70, 130, 255, 0.50)",sizeW:24,sizeH:24,offsetX:51,offsetY:-1},{color:"rgba(120, 80, 255, 0.45)",sizeW:30,sizeH:20,offsetX:21,offsetY:0},{color:"rgba(90, 110, 230, 0.40)",sizeW:25,sizeH:18,offsetX:-21,offsetY:-2},{color:"rgba(110, 90, 240, 0.45)",sizeW:21,sizeH:24,offsetX:66,offsetY:0},{color:"rgba(140, 100, 255, 0.52)",sizeW:18,sizeH:26,offsetX:-66,offsetY:-1}],sunset:[{color:"rgba(255, 100, 60, 0.48)",sizeW:33,sizeH:30,offsetX:0,offsetY:0},{color:"rgba(255, 180, 50, 0.42)",sizeW:24,sizeH:26,offsetX:39,offsetY:-3},{color:"rgba(255, 140, 70, 0.48)",sizeW:27,sizeH:24,offsetX:-36,offsetY:0},{color:"rgba(255, 80, 80, 0.42)",sizeW:23,sizeH:28,offsetX:-54,offsetY:-2},{color:"rgba(255, 200, 60, 0.50)",sizeW:24,sizeH:24,offsetX:51,offsetY:-1},{color:"rgba(255, 120, 50, 0.45)",sizeW:30,sizeH:20,offsetX:21,offsetY:0},{color:"rgba(255, 160, 80, 0.40)",sizeW:25,sizeH:18,offsetX:-21,offsetY:-2},{color:"rgba(255, 90, 60, 0.45)",sizeW:21,sizeH:24,offsetX:66,offsetY:0},{color:"rgba(255, 70, 70, 0.52)",sizeW:18,sizeH:26,offsetX:-66,offsetY:-1}]};function Ot(a,e){return Mt[a].map(o=>{let r=o.offsetX===0?"":o.offsetX>0?` + ${o.offsetX}px`:` - ${Math.abs(o.offsetX)}px`,n=o.offsetY===0?"":` - ${Math.abs(o.offsetY)}px`;return`radial-gradient(ellipse calc(${o.sizeW}px * var(--beam-w-${e})) calc(${o.sizeH}px * var(--beam-h-${e})) at calc(var(--beam-x-${e}) * 100%${r}) calc(100%${n}), ${o.color}, transparent)`}).join(`,
    `)}var St={colorful:{dark:{spikes:[{color1:"rgb(100, 70, 255)",color2:"rgba(100, 70, 255, 1)"},{color1:"rgba(255, 170, 40, 0.59)",color2:"rgba(255, 170, 40, 0.29)"},{color1:"rgb(50, 200, 100)",color2:"rgba(50, 200, 100, 1)"},{color1:"rgba(200, 50, 240, 0.91)",color2:"rgba(200, 50, 240, 0.45)"},{color1:"rgb(40, 140, 255)",color2:"rgba(40, 140, 255, 1)"}]},light:{spikes:[{color1:"rgb(80, 50, 200)",color2:"rgba(80, 50, 200, 0.8)"},{color1:"rgba(210, 130, 0, 0.7)",color2:"rgba(210, 130, 0, 0.46)"},{color1:"rgb(30, 160, 70)",color2:"rgba(30, 160, 70, 0.82)"},{color1:"rgb(160, 30, 190)",color2:"rgba(160, 30, 190, 0.7)"},{color1:"rgb(30, 100, 200)",color2:"rgba(30, 100, 200, 0.78)"}]}},mono:{dark:{spikes:[{color1:"rgb(200, 200, 200)",color2:"rgba(200, 200, 200, 1)"},{color1:"rgba(180, 180, 180, 0.59)",color2:"rgba(180, 180, 180, 0.29)"},{color1:"rgb(190, 190, 190)",color2:"rgba(190, 190, 190, 1)"},{color1:"rgba(170, 170, 170, 0.91)",color2:"rgba(170, 170, 170, 0.45)"},{color1:"rgb(185, 185, 185)",color2:"rgba(185, 185, 185, 1)"}]},light:{spikes:[{color1:"rgb(80, 80, 80)",color2:"rgba(80, 80, 80, 0.8)"},{color1:"rgba(100, 100, 100, 0.7)",color2:"rgba(100, 100, 100, 0.46)"},{color1:"rgb(70, 70, 70)",color2:"rgba(70, 70, 70, 0.82)"},{color1:"rgb(90, 90, 90)",color2:"rgba(90, 90, 90, 0.7)"},{color1:"rgb(85, 85, 85)",color2:"rgba(85, 85, 85, 0.78)"}]}},ocean:{dark:{spikes:[{color1:"rgb(100, 80, 255)",color2:"rgb(100, 80, 255)"},{color1:"rgba(80, 130, 220, 0.59)",color2:"rgba(80, 130, 220, 0.29)"},{color1:"rgb(60, 100, 255)",color2:"rgb(60, 100, 255)"},{color1:"rgba(90, 120, 200, 0.91)",color2:"rgba(90, 120, 200, 0.45)"},{color1:"rgb(120, 90, 255)",color2:"rgb(120, 90, 255)"}]},light:{spikes:[{color1:"rgb(50, 40, 180)",color2:"rgba(50, 40, 180, 0.8)"},{color1:"rgba(40, 80, 200, 0.7)",color2:"rgba(40, 80, 200, 0.46)"},{color1:"rgb(30, 50, 190)",color2:"rgba(30, 50, 190, 0.82)"},{color1:"rgb(60, 90, 180)",color2:"rgba(60, 90, 180, 0.7)"},{color1:"rgb(70, 60, 200)",color2:"rgba(70, 60, 200, 0.78)"}]}},sunset:{dark:{spikes:[{color1:"rgb(255, 100, 80)",color2:"rgb(255, 100, 80)"},{color1:"rgba(255, 150, 80, 0.59)",color2:"rgba(255, 150, 80, 0.29)"},{color1:"rgb(255, 80, 60)",color2:"rgb(255, 80, 60)"},{color1:"rgba(255, 120, 50, 0.91)",color2:"rgba(255, 120, 50, 0.45)"},{color1:"rgb(255, 140, 70)",color2:"rgb(255, 140, 70)"}]},light:{spikes:[{color1:"rgb(200, 60, 30)",color2:"rgba(200, 60, 30, 0.8)"},{color1:"rgba(220, 100, 20, 0.7)",color2:"rgba(220, 100, 20, 0.46)"},{color1:"rgb(180, 40, 20)",color2:"rgba(180, 40, 20, 0.82)"},{color1:"rgb(210, 80, 10)",color2:"rgba(210, 80, 10, 0.7)"},{color1:"rgb(190, 70, 30)",color2:"rgba(190, 70, 30, 0.78)"}]}}};function pe(a,e){let t=a.match(/^rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*[\d.]+\s*\)$/);if(t)return`rgba(${t[1]}, ${t[2]}, ${t[3]}, ${e})`;let o=a.match(/^rgb\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)$/);return o?`rgba(${o[1]}, ${o[2]}, ${o[3]}, ${e})`:a}function j(a,e){let t=a.match(/^rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)$/);if(t)return`rgba(${t[1]}, ${t[2]}, ${t[3]}, ${(parseFloat(t[4])*e).toFixed(2)})`;let o=a.match(/^rgb\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)$/);return o?`rgba(${o[1]}, ${o[2]}, ${o[3]}, ${e.toFixed(2)})`:a}function Wt(a,e,t){let o=zt(a,e),r=St[a][e?"dark":"light"],n=a==="mono",s=n?.14:1,i=n?j(o.primary,.14):o.primary,l=n?j(o.primary,.09):o.primary,d=n?j(o.secondary,.12):o.secondary,g=n?pe(o.secondary,.06):pe(o.secondary,.49),c=r.spikes.map(h=>n?{color1:j(h.color1,s),color2:j(h.color2,s*.7)}:h),b=n?"12px":"0.8px",p=n?"14px":"2px",x=n?"12px":"1.2px",u=n?"10px":"0.6px",z=n?"42px":"92px",S=n?"38px":"72px",k=n?"40px":"85px",w=n?"32px":"60px",M=n?"12px":"1px",y=n?"rgba(255, 255, 255, 0.5)":"rgba(255, 255, 255, 1)",v=n?"rgba(255, 255, 255, 0.45)":"rgba(255, 255, 255, 0.9)",O=n?"rgba(255, 255, 255, 0.25)":"rgba(255, 255, 255, 0.5)",m=n?"rgba(255, 255, 255, 0.15)":"rgba(255, 255, 255, 0.3)",$=n?"rgba(255, 255, 255, 0.06)":"rgba(255, 255, 255, 0.12)",f=n?"rgba(255, 255, 255, 0.015)":"rgba(255, 255, 255, 0.03)";if(e)return`radial-gradient(ellipse calc(${b} * var(--beam-spike-${t})) calc(${z} * var(--beam-h-${t})) at 8% calc(100% - 2px), ${i}, ${l} 30%, transparent 88%),
       radial-gradient(ellipse calc(10px * var(--beam-spike2-${t})) calc(35px * var(--beam-h-${t})) at 22% calc(100% - 4px), ${d}, ${g} 50%, transparent 95%),
       radial-gradient(ellipse calc(${p} * (2 - var(--beam-spike-${t}))) calc(${S} * var(--beam-h-${t})) at 36% calc(100% - 3px), ${c[0].color1}, ${c[0].color2} 40%, transparent 90%),
       radial-gradient(ellipse calc(14px * var(--beam-spike2-${t})) calc(28px * var(--beam-h-${t})) at 50% calc(100% - 2px), ${c[1].color1}, ${c[1].color2} 55%, transparent 96%),
       radial-gradient(ellipse calc(${x} * (2 - var(--beam-spike2-${t}))) calc(${k} * var(--beam-h-${t})) at 64% calc(100% - 4px), ${c[2].color1}, ${c[2].color2} 35%, transparent 89%),
       radial-gradient(ellipse calc(7px * var(--beam-spike-${t})) calc(45px * var(--beam-h-${t})) at 78% calc(100% - 2px), ${c[3].color1}, ${c[3].color2} 48%, transparent 94%),
       radial-gradient(ellipse calc(${u} * (2 - var(--beam-spike-${t}))) calc(${w} * var(--beam-h-${t})) at 92% calc(100% - 3px), ${c[4].color1}, ${c[4].color2} 42%, transparent 91%),
       radial-gradient(ellipse calc(21px * var(--beam-spike-${t})) calc(15px * var(--beam-spike2-${t})) at calc(var(--beam-x-${t}) * 100%) calc(100% + 1px), ${y} 0%, ${v} 20%, ${O} 50%, transparent 100%),
       radial-gradient(ellipse calc(42px * var(--beam-w-${t})) calc(40px * var(--beam-h-${t})) at calc(var(--beam-x-${t}) * 100%) 100%, ${m} 0%, ${$} 25%, ${f} 55%, transparent 80%)`;{let h=n?j(o.primary,.11):pe(o.primary,.85),W=n?j(o.secondary,.09):pe(o.secondary,.7);return`radial-gradient(ellipse calc(${b} * var(--beam-spike-${t})) calc(${z} * var(--beam-h-${t})) at 8% calc(100% - 2px), ${i}, ${h} 30%, transparent 88%),
       radial-gradient(ellipse calc(10px * var(--beam-spike2-${t})) calc(35px * var(--beam-h-${t})) at 22% calc(100% - 4px), ${d}, ${W} 50%, transparent 95%),
       radial-gradient(ellipse calc(${p} * (2 - var(--beam-spike-${t}))) calc(${S} * var(--beam-h-${t})) at 36% calc(100% - 3px), ${c[0].color1}, ${c[0].color2} 40%, transparent 90%),
       radial-gradient(ellipse calc(14px * var(--beam-spike2-${t})) calc(28px * var(--beam-h-${t})) at 50% calc(100% - 2px), ${c[1].color1}, ${c[1].color2} 55%, transparent 96%),
       radial-gradient(ellipse calc(${x} * (2 - var(--beam-spike2-${t}))) calc(${k} * var(--beam-h-${t})) at 64% calc(100% - 4px), ${c[2].color1}, ${c[2].color2} 35%, transparent 89%),
       radial-gradient(ellipse calc(7px * var(--beam-spike-${t})) calc(45px * var(--beam-h-${t})) at 78% calc(100% - 2px), ${c[3].color1}, ${c[3].color2} 48%, transparent 94%),
       radial-gradient(ellipse calc(${M} * (2 - var(--beam-spike-${t}))) calc(${w} * var(--beam-h-${t})) at 92% calc(100% - 3px), ${c[4].color1}, ${c[4].color2} 42%, transparent 91%),
       radial-gradient(ellipse calc(50px * var(--beam-w-${t})) calc(32px * var(--beam-h-${t})) at calc(var(--beam-x-${t}) * 100%) calc(100%), rgba(0, 0, 0, 0.5) 0%, rgba(0, 0, 0, 0.18) 30%, rgba(0, 0, 0, 0.03) 60%, transparent 85%)`}}var Le=[{region:1,quad:"tl"},{region:2,quad:"tl"},{region:3,quad:"bl"},{region:1,quad:"bl"},{region:2,quad:"br"},{region:3,quad:"br"},{region:1,quad:"tr"},{region:2,quad:"tr"},{region:3,quad:"tr"}],Rt=[[65,35],[55,30],[35,65],[15,30],[173,28],[80,22],[69,28],[22,38],[47,44]],Ht=[{ci:0,region:1,quad:"tl",w:84,h:48},{ci:1,region:2,quad:"tl",w:72,h:42},{ci:2,region:3,quad:"bl",w:48,h:84},{ci:4,region:2,quad:"br",w:216,h:38},{ci:5,region:3,quad:"br",w:102,h:31},{ci:6,region:1,quad:"tr",w:89,h:38},{ci:8,region:3,quad:"tr",w:62,h:58}],Ce=[{ci:0,region:1,quad:"tl",w:80,h:19,x:"27%",y:"0%"},{ci:6,region:2,quad:"tr",w:74,h:11,x:"73%",y:"-1%"},{ci:7,region:3,quad:"tr",w:15,h:44,x:"100%",y:"33%"},{ci:8,region:1,quad:"br",w:19,h:38,x:"101%",y:"72%"},{ci:4,region:2,quad:"br",w:84,h:13,x:"67%",y:"100%"},{ci:1,region:3,quad:"bl",w:60,h:21,x:"24%",y:"101%"},{ci:2,region:1,quad:"bl",w:17,h:40,x:"0%",y:"60%"},{ci:3,region:2,quad:"tl",w:13,h:32,x:"-1%",y:"28%"}],Pt=[{ci:0,region:1,quad:"tl",w:110,h:30,x:"27%",y:"3%"},{ci:6,region:2,quad:"tr",w:100,h:20,x:"73%",y:"1%"},{ci:7,region:3,quad:"tr",w:26,h:62,x:"100%",y:"33%"},{ci:8,region:1,quad:"br",w:30,h:56,x:"101%",y:"72%"},{ci:4,region:2,quad:"br",w:120,h:22,x:"67%",y:"99%"},{ci:1,region:3,quad:"bl",w:88,h:32,x:"24%",y:"99%"},{ci:2,region:1,quad:"bl",w:28,h:58,x:"0%",y:"60%"}];function Yt(a,e,t){let o=a.match(/^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/);return`rgba(${o?`${o[1]}, ${o[2]}, ${o[3]}`:"255, 255, 255"}, var(--bop-${e}-${t}))`}function $e(a,e,t,o,r,n,s,i){return`radial-gradient(ellipse calc(${e}px * var(--bw${o}-${i}) * var(--pulse-glow-sx, 1) * var(--pulse-glow-boost, 1)) calc(${t}px * var(--bh${o}-${i}) * var(--bgh-${i}) * var(--pulse-glow-sy, 1) * var(--pulse-glow-boost, 1)) at calc(${n} + var(--bx${o}-${i})) calc(${s} + var(--by${o}-${i})), ${Yt(a,r,i)}, transparent)`}function Xt(a,e){return K[a].border.map((t,o)=>{let{region:r,quad:n}=Le[o],[s,i]=t.pos.split(" "),[l,d]=t.size.split(" ").map(parseFloat);return $e(t.color,l,d,r,n,s,i,e)}).join(`,
    `)}function Bt(a,e,t){let r=K[a].border.map((d,g)=>{let{region:c,quad:b}=Le[g],[p,x]=d.pos.split(" "),[u,z]=Rt[g];return $e(d.color,u,z,c,b,p,x,e)}),n=t?"255, 255, 255":"0, 0, 0",s=t?.18:.08,l=[["0%","0%","tl"],["100%","0%","tr"],["0%","100%","bl"],["100%","100%","br"]].map(([d,g,c])=>`radial-gradient(ellipse 60px 60px at ${d} ${g}, rgba(${n}, calc(${s} * var(--bop-${c}-${e}))), transparent 70%)`);return[...r,...l].join(`,
    `)}function Ee(a,e,t){let o=K[e].border;return a.map(r=>{let n=o[r.ci],[s,i]=n.pos.split(" ");return $e(n.color,r.w,r.h,r.region,r.quad,r.x??s,r.y??i,t)}).join(`,
    `)}function Te(a,e,t){let o=K[e].border,r=+t.toFixed(3);return a.map(n=>{let s=o[n.ci],[i,l]=s.pos.split(" "),d=n.x??i,g=n.y??l,c=s.color.match(/^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/),b=c?`${c[1]}, ${c[2]}, ${c[3]}`:"255, 255, 255";return`radial-gradient(ellipse calc(${n.w}px * var(--pulse-glow-sx, 1) * var(--pulse-glow-boost, 1)) calc(${n.h}px * var(--pulse-glow-sy, 1) * var(--pulse-glow-boost, 1)) at ${d} ${g}, rgba(${b}, ${r}), transparent)`}).join(`,
    `)}function re(a){return`
[data-beam="${a}"][data-paused],
[data-beam="${a}"][data-paused]::after,
[data-beam="${a}"][data-paused]::before,
[data-beam="${a}"][data-paused] [data-beam-bloom] {
  animation-play-state: paused !important;
}`}function Ae(a){let e=["bw1","bh1","bw2","bh2","bw3","bh3","bgh","bop-tl","bop-tr","bop-bl","bop-br"],t=["bx1","by1","bx2","by2","bx3","by3"],o=e.map(n=>`@property --${n}-${a} {
  syntax: "<number>";
  initial-value: 1;
  inherits: true;
}`).join(`

`),r=t.map(n=>`@property --${n}-${a} {
  syntax: "<length>";
  initial-value: 0px;
  inherits: true;
}`).join(`

`);return`${o}

${r}

@property --beam-opacity-${a} {
  syntax: "<number>";
  initial-value: 0;
  inherits: true;
}

@property --beam-hue-${a} {
  syntax: "<angle>";
  initial-value: 0deg;
  inherits: true;
}`}function ye(a,e,t){let o=e==="dark",r=t/2.3;return a==="pulse-inner"?{sp:.28,dr:o?33:40,op:o?.48:.45,gh:o?.34:.22,bs:(o?1.9:2.6)*r,ss:(o?2.6:4.6)*r,ghs:(o?2.4:5.5)*r,huePeriod:16}:{sp:o?.28:.36,dr:o?14:19,op:o?.46:0,gh:o?.16:.58,bs:(o?2.3:3.7)*r,ss:(o?6.4:4.6)*r,ghs:(o?2.4:3.8)*r,huePeriod:14}}function Dt(a,e){let{sp:t,dr:o,op:r,gh:n,bs:s,ss:i,ghs:l}=e;return[{prop:`--bw1-${a}`,a:1-t,b:1+t*1.1,period:i*.9,delay:0,unit:""},{prop:`--bh1-${a}`,a:1+t*.9,b:1-t*.85,period:i*1.26,delay:0,unit:""},{prop:`--bx1-${a}`,a:-o,b:o*.9,period:s*1.6,delay:0,unit:"px"},{prop:`--by1-${a}`,a:o*.55,b:-o*.7,period:s*1.6,delay:0,unit:"px"},{prop:`--bw2-${a}`,a:1+t,b:1-t*.85,period:i*1.1,delay:0,unit:""},{prop:`--bh2-${a}`,a:1-t*.8,b:1+t*1.05,period:i*.81,delay:0,unit:""},{prop:`--bx2-${a}`,a:o*.8,b:-o*.9,period:s*1.88,delay:0,unit:"px"},{prop:`--by2-${a}`,a:-o,b:o*.65,period:s*1.88,delay:0,unit:"px"},{prop:`--bw3-${a}`,a:1-t*.6,b:1+t*1.15,period:i*.98,delay:0,unit:""},{prop:`--bh3-${a}`,a:1+t*.75,b:1-t,period:i*1.4,delay:0,unit:""},{prop:`--bx3-${a}`,a:-o*.6,b:o,period:s*1.45,delay:0,unit:"px"},{prop:`--by3-${a}`,a:-o*.85,b:o*.45,period:s*1.45,delay:0,unit:"px"},{prop:`--bgh-${a}`,a:1-n,b:1+n,period:l,delay:0,unit:""},{prop:`--bop-tl-${a}`,a:1-r,b:1,period:s,delay:0,unit:""},{prop:`--bop-tr-${a}`,a:1-r,b:1,period:s*1.32,delay:s*.28,unit:""},{prop:`--bop-bl-${a}`,a:1-r,b:1,period:s*.84,delay:s*.55,unit:""},{prop:`--bop-br-${a}`,a:1-r,b:1,period:s*1.58,delay:s*.83,unit:""}]}function Ge(a,e,t,o,r,n){if(a!=="pulse-inner"&&a!=="pulse-outside")return null;let s=ye(a,e,t);return{oscillators:Dt(n,s),hue:r?null:{prop:`--beam-hue-${n}`,range:360,period:s.huePeriod,continuous:!0}}}function de(a,e,t){return`  animation: ${e}-${a} ${t}s ease forwards;`}function qe(a){let{size:e}=a;return e==="line"?Lt(a):e==="sm"?Ct(a):e==="pulse-inner"?Ft(a):e==="pulse-outside"?It(a):Et(a)}function Ct(a){let{id:e,borderRadius:t,borderWidth:o,duration:r,strokeOpacity:n,innerOpacity:s,bloomOpacity:i,innerShadow:l,colorVariant:d,staticColors:g,brightness:c,saturation:b,hueRange:p,theme:x}=a,u=Math.max(0,t-o),z=d==="mono"?.5:1,S=n*z,k=s*z,w=i*z,M=g?"":`animation: beam-hue-shift-${e} 12s ease-in-out infinite;`,y=g?"":`
@keyframes beam-hue-shift-${e} {
  0% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p}deg)) brightness(${c.toFixed(2)}) saturate(${b.toFixed(2)}); }
  50% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) + ${p}deg)) brightness(${c.toFixed(2)}) saturate(${b.toFixed(2)}); }
  100% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p}deg)) brightness(${c.toFixed(2)}) saturate(${b.toFixed(2)}); }
}`,v=x==="dark",O=v?`conic-gradient(
        from var(--beam-angle-${e}),
        transparent 0%, transparent 54%,
        rgba(255, 255, 255, 0.1) 57%,
        rgba(255, 255, 255, 0.3) 60%,
        rgba(255, 255, 255, 0.6) 63%,
        rgba(255, 255, 255, 0.75) 66%,
        rgba(255, 255, 255, 0.6) 69%,
        rgba(255, 255, 255, 0.3) 72%,
        rgba(255, 255, 255, 0.1) 75%,
        transparent 78%, transparent 100%
      )`:`conic-gradient(
        from var(--beam-angle-${e}),
        transparent 0%, transparent 54%,
        rgba(0, 0, 0, 0.08) 57%,
        rgba(0, 0, 0, 0.2) 60%,
        rgba(0, 0, 0, 0.4) 63%,
        rgba(0, 0, 0, 0.55) 66%,
        rgba(0, 0, 0, 0.4) 69%,
        rgba(0, 0, 0, 0.2) 72%,
        rgba(0, 0, 0, 0.08) 75%,
        transparent 78%, transparent 100%
      )`,m=xt(d),$=$t(d),f=v?`conic-gradient(
        from var(--beam-angle-${e}),
        transparent 0%, transparent 58%,
        rgba(255, 255, 255, 0.03) 62%,
        rgba(255, 255, 255, 0.08) 65%,
        rgba(255, 255, 255, 0.2) 67%,
        rgba(255, 255, 255, 0.45) 69%,
        rgba(255, 255, 255, 0.85) 70%,
        rgba(255, 255, 255, 0.85) 70.5%,
        rgba(255, 255, 255, 0.45) 71.5%,
        rgba(255, 255, 255, 0.2) 73%,
        rgba(255, 255, 255, 0.08) 75%,
        rgba(255, 255, 255, 0.03) 78%,
        transparent 82%
      )`:`conic-gradient(
        from var(--beam-angle-${e}),
        transparent 0%, transparent 58%,
        rgba(0, 0, 0, 0.02) 62%,
        rgba(0, 0, 0, 0.08) 65%,
        rgba(0, 0, 0, 0.2) 67%,
        rgba(0, 0, 0, 0.4) 69%,
        rgba(0, 0, 0, 0.6) 70%,
        rgba(0, 0, 0, 0.6) 70.5%,
        rgba(0, 0, 0, 0.4) 71.5%,
        rgba(0, 0, 0, 0.2) 73%,
        rgba(0, 0, 0, 0.08) 75%,
        rgba(0, 0, 0, 0.02) 78%,
        transparent 82%
      )`,h=`conic-gradient(
    from var(--beam-angle-${e}),
    transparent 0%, transparent 22%,
    rgba(255, 255, 255, 0.12) 28%, rgba(255, 255, 255, 0.4) 36%,
    white 46%, white 82%,
    rgba(255, 255, 255, 0.4) 88%, rgba(255, 255, 255, 0.12) 94%,
    transparent 97%, transparent 100%
  )`;return`
@property --beam-angle-${e} {
  syntax: "<angle>";
  initial-value: 0deg;
  inherits: true;
}

@property --beam-opacity-${e} {
  syntax: "<number>";
  initial-value: 0;
  inherits: true;
}

[data-beam="${e}"] {
  position: relative;
  border-radius: ${t}px;
  overflow: hidden;
}

[data-beam="${e}"][data-active] {
  animation:
    beam-spin-${e} ${r}s linear infinite,
    beam-fade-in-${e} 0.6s ease forwards;
}

[data-beam="${e}"][data-fading] {
  animation:
    beam-spin-${e} ${r}s linear infinite,
    beam-fade-out-${e} 0.5s ease forwards;
}

[data-beam="${e}"][data-active]::after,
[data-beam="${e}"][data-fading]::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${u}px;
  padding: ${o}px;
  clip-path: inset(0 round ${t}px);
  background: ${O},${m};
  -webkit-mask:
    conic-gradient(
      from var(--beam-angle-${e}),
      transparent 0%, transparent 30%,
      rgba(255, 255, 255, 0.1) 36%, rgba(255, 255, 255, 0.35) 44%,
      white 52%, white 80%,
      rgba(255, 255, 255, 0.35) 86%, rgba(255, 255, 255, 0.1) 92%,
      transparent 95%, transparent 100%
    ),
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  -webkit-mask-composite: source-in, xor;
  mask:
    conic-gradient(
      from var(--beam-angle-${e}),
      transparent 0%, transparent 30%,
      rgba(255, 255, 255, 0.1) 36%, rgba(255, 255, 255, 0.35) 44%,
      white 52%, white 80%,
      rgba(255, 255, 255, 0.35) 86%, rgba(255, 255, 255, 0.1) 92%,
      transparent 95%, transparent 100%
    ),
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  mask-composite: intersect, exclude;
  pointer-events: none;
  z-index: 2;
  opacity: calc(var(--beam-opacity-${e}) * ${S.toFixed(2)} * var(--beam-stroke-opacity, 1) * var(--beam-strength, 1));
  ${M}
}

[data-beam="${e}"][data-active]::before,
[data-beam="${e}"][data-fading]::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${t}px;
  clip-path: inset(0 round ${t}px);
  background: ${$};
  box-shadow: inset 0 0 5px 1px ${l};
  -webkit-mask-image: ${h};
  -webkit-mask-composite: source-over;
  mask-image: ${h};
  mask-composite: add;
  pointer-events: none;
  z-index: 1;
  opacity: calc(var(--beam-opacity-${e}) * ${k.toFixed(2)} * var(--beam-inner-opacity, 1) * var(--beam-strength, 1));
  ${M}
}

[data-beam="${e}"] [data-beam-bloom] {
  display: none;
  position: absolute;
  inset: 0;
  border-radius: ${u}px;
  clip-path: inset(0 round ${t}px);
  background: ${f};
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  padding: ${o}px;
  filter: blur(8px) brightness(${c.toFixed(2)}) saturate(${b.toFixed(2)});
  pointer-events: none;
  z-index: 3;
  opacity: 0;
}

[data-beam="${e}"][data-active] [data-beam-bloom],
[data-beam="${e}"][data-fading] [data-beam-bloom] {
  display: block;
  opacity: calc(var(--beam-opacity-${e}) * ${w.toFixed(2)} * var(--beam-bloom-opacity, 1) * var(--beam-strength, 1));
}

@keyframes beam-spin-${e} {
  to { --beam-angle-${e}: 360deg; }
}

@keyframes beam-fade-in-${e} {
  to { --beam-opacity-${e}: 1; }
}

@keyframes beam-fade-out-${e} {
  from { --beam-opacity-${e}: 1; }
  to { --beam-opacity-${e}: 0; }
}
${y}
${re(e)}
`}function Et(a){let{id:e,borderRadius:t,borderWidth:o,duration:r,strokeOpacity:n,innerOpacity:s,bloomOpacity:i,innerShadow:l,colorVariant:d,staticColors:g,brightness:c,saturation:b,hueRange:p,theme:x}=a,u=Math.max(0,t-o),z=d==="mono"?.5:1,S=n*z,k=s*z,w=i*z,M=g?"":`animation: beam-hue-shift-${e} 12s ease-in-out infinite;`,y=g?"":`
@keyframes beam-hue-shift-${e} {
  0% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p}deg)) brightness(${c.toFixed(2)}) saturate(${b.toFixed(2)}); }
  50% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) + ${p}deg)) brightness(${c.toFixed(2)}) saturate(${b.toFixed(2)}); }
  100% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p}deg)) brightness(${c.toFixed(2)}) saturate(${b.toFixed(2)}); }
}`,v=x==="dark",O=v?`conic-gradient(
        from var(--beam-angle-${e}),
        transparent 0%, transparent 54%,
        rgba(255, 255, 255, 0.1) 57%,
        rgba(255, 255, 255, 0.3) 60%,
        rgba(255, 255, 255, 0.6) 63%,
        rgba(255, 255, 255, 0.75) 66%,
        rgba(255, 255, 255, 0.6) 69%,
        rgba(255, 255, 255, 0.3) 72%,
        rgba(255, 255, 255, 0.1) 75%,
        transparent 78%, transparent 100%
      )`:`conic-gradient(
        from var(--beam-angle-${e}),
        transparent 0%, transparent 54%,
        rgba(0, 0, 0, 0.08) 57%,
        rgba(0, 0, 0, 0.2) 60%,
        rgba(0, 0, 0, 0.4) 63%,
        rgba(0, 0, 0, 0.55) 66%,
        rgba(0, 0, 0, 0.4) 69%,
        rgba(0, 0, 0, 0.2) 72%,
        rgba(0, 0, 0, 0.08) 75%,
        transparent 78%, transparent 100%
      )`,m=yt(d),$=vt(d),f=v?`conic-gradient(
        from var(--beam-angle-${e}),
        transparent 0%, transparent 58%,
        rgba(255, 255, 255, 0.03) 62%,
        rgba(255, 255, 255, 0.08) 65%,
        rgba(255, 255, 255, 0.2) 67%,
        rgba(255, 255, 255, 0.45) 69%,
        rgba(255, 255, 255, 0.85) 70%,
        rgba(255, 255, 255, 0.85) 70.5%,
        rgba(255, 255, 255, 0.45) 71.5%,
        rgba(255, 255, 255, 0.2) 73%,
        rgba(255, 255, 255, 0.08) 75%,
        rgba(255, 255, 255, 0.03) 78%,
        transparent 82%
      )`:`conic-gradient(
        from var(--beam-angle-${e}),
        transparent 0%, transparent 58%,
        rgba(0, 0, 0, 0.02) 62%,
        rgba(0, 0, 0, 0.08) 65%,
        rgba(0, 0, 0, 0.2) 67%,
        rgba(0, 0, 0, 0.4) 69%,
        rgba(0, 0, 0, 0.6) 70%,
        rgba(0, 0, 0, 0.6) 70.5%,
        rgba(0, 0, 0, 0.4) 71.5%,
        rgba(0, 0, 0, 0.2) 73%,
        rgba(0, 0, 0, 0.08) 75%,
        rgba(0, 0, 0, 0.02) 78%,
        transparent 82%
      )`;return`
@property --beam-angle-${e} {
  syntax: "<angle>";
  initial-value: 0deg;
  inherits: true;
}

@property --beam-opacity-${e} {
  syntax: "<number>";
  initial-value: 0;
  inherits: true;
}

[data-beam="${e}"] {
  position: relative;
  border-radius: ${t}px;
  overflow: hidden;
}

[data-beam="${e}"][data-active] {
  animation:
    beam-spin-${e} ${r}s linear infinite,
    beam-fade-in-${e} 0.6s ease forwards;
}

[data-beam="${e}"][data-fading] {
  animation:
    beam-spin-${e} ${r}s linear infinite,
    beam-fade-out-${e} 0.5s ease forwards;
}

[data-beam="${e}"][data-active]::after,
[data-beam="${e}"][data-fading]::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${u}px;
  padding: ${o}px;
  clip-path: inset(0 round ${t}px);
  background: ${O},${m};
  -webkit-mask:
    conic-gradient(
      from var(--beam-angle-${e}),
      transparent 0%, transparent 30%,
      rgba(255, 255, 255, 0.1) 36%, rgba(255, 255, 255, 0.35) 44%,
      white 52%, white 80%,
      rgba(255, 255, 255, 0.35) 86%, rgba(255, 255, 255, 0.1) 92%,
      transparent 95%, transparent 100%
    ),
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  -webkit-mask-composite: source-in, xor;
  mask:
    conic-gradient(
      from var(--beam-angle-${e}),
      transparent 0%, transparent 30%,
      rgba(255, 255, 255, 0.1) 36%, rgba(255, 255, 255, 0.35) 44%,
      white 52%, white 80%,
      rgba(255, 255, 255, 0.35) 86%, rgba(255, 255, 255, 0.1) 92%,
      transparent 95%, transparent 100%
    ),
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  mask-composite: intersect, exclude;
  pointer-events: none;
  z-index: 2;
  opacity: calc(var(--beam-opacity-${e}) * ${S.toFixed(2)} * var(--beam-stroke-opacity, 1) * var(--beam-strength, 1));
  ${M}
}

[data-beam="${e}"][data-active]::before,
[data-beam="${e}"][data-fading]::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${t}px;
  background: ${$};
  box-shadow: inset 0 0 9px 1px ${l};
  -webkit-mask-image:
    conic-gradient(
      from var(--beam-angle-${e}),
      transparent 0%, transparent 30%,
      rgba(255, 255, 255, 0.1) 36%, rgba(255, 255, 255, 0.35) 44%,
      white 52%, white 80%,
      rgba(255, 255, 255, 0.35) 86%, rgba(255, 255, 255, 0.1) 92%,
      transparent 95%, transparent 100%
    ),
    linear-gradient(white, transparent 28px, transparent calc(100% - 28px), white),
    linear-gradient(to right, white, transparent 28px, transparent calc(100% - 28px), white);
  -webkit-mask-composite: source-in, source-over;
  mask-image:
    conic-gradient(
      from var(--beam-angle-${e}),
      transparent 0%, transparent 30%,
      rgba(255, 255, 255, 0.1) 36%, rgba(255, 255, 255, 0.35) 44%,
      white 52%, white 80%,
      rgba(255, 255, 255, 0.35) 86%, rgba(255, 255, 255, 0.1) 92%,
      transparent 95%, transparent 100%
    ),
    linear-gradient(white, transparent 28px, transparent calc(100% - 28px), white),
    linear-gradient(to right, white, transparent 28px, transparent calc(100% - 28px), white);
  mask-composite: intersect, add;
  pointer-events: none;
  z-index: 1;
  opacity: calc(var(--beam-opacity-${e}) * ${k.toFixed(2)} * var(--beam-inner-opacity, 1) * var(--beam-strength, 1));
  clip-path: inset(0 round ${t}px);
  ${M}
}

[data-beam="${e}"] [data-beam-bloom] {
  display: none;
  position: absolute;
  inset: 0;
  border-radius: ${u}px;
  clip-path: inset(0 round ${t}px);
  background: ${f};
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  padding: ${o}px;
  filter: blur(8px) brightness(${c.toFixed(2)}) saturate(${b.toFixed(2)});
  pointer-events: none;
  z-index: 3;
  opacity: 0;
}

[data-beam="${e}"][data-active] [data-beam-bloom],
[data-beam="${e}"][data-fading] [data-beam-bloom] {
  display: block;
  opacity: calc(var(--beam-opacity-${e}) * ${w.toFixed(2)} * var(--beam-bloom-opacity, 1) * var(--beam-strength, 1));
}

@keyframes beam-spin-${e} {
  to { --beam-angle-${e}: 360deg; }
}

@keyframes beam-fade-in-${e} {
  to { --beam-opacity-${e}: 1; }
}

@keyframes beam-fade-out-${e} {
  from { --beam-opacity-${e}: 1; }
  to { --beam-opacity-${e}: 0; }
}
${y}
${re(e)}
`}function Ft(a){let{id:e,borderRadius:t,borderWidth:o,duration:r,strokeOpacity:n,innerOpacity:s,bloomOpacity:i,colorVariant:l,staticColors:d,brightness:g,saturation:c,hueRange:b,theme:p}=a,x=p==="dark",u=l==="mono"?.5:1,z=(n*u).toFixed(2),S=(s*u).toFixed(2),k=(i*u).toFixed(2),{op:w}=ye("pulse-inner",p,r),M=8,y=g.toFixed(2),v=c.toFixed(2),O=d?`filter: brightness(${y}) saturate(${v});`:`filter: hue-rotate(calc(var(--beam-hue-base, 0deg) + var(--beam-hue-${e}))) brightness(${y}) saturate(${v});`,m=d?`filter: blur(${M}px) brightness(${y}) saturate(${v});`:`filter: blur(${M}px) hue-rotate(calc(var(--beam-hue-base, 0deg) + var(--beam-hue-${e}))) brightness(${y}) saturate(${v});`,$=Xt(l,e),f=Bt(l,e,x),h=Te(Ht,l,1-w*.5);return`
${Ae(e)}

[data-beam="${e}"] {
  position: relative;
  border-radius: ${t}px;
  overflow: hidden;
  isolation: isolate;
}

[data-beam="${e}"][data-active] {
${de(e,"beam-fade-in",.6)}
}

[data-beam="${e}"][data-fading] {
${de(e,"beam-fade-out",.5)}
}

[data-beam="${e}"][data-active]::after,
[data-beam="${e}"][data-fading]::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${t}px;
  padding: ${o}px;
  clip-path: inset(0 round ${t}px);
  background: ${$};
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  pointer-events: none;
  z-index: 2;
  will-change: opacity, filter;
  opacity: calc(var(--beam-opacity-${e}) * ${z} * var(--beam-stroke-opacity, 1) * var(--beam-strength, 1));
  ${O}
}

[data-beam="${e}"][data-active]::before,
[data-beam="${e}"][data-fading]::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${t}px;
  clip-path: inset(0 round ${t}px);
  background: ${f};
  -webkit-mask-image:
    linear-gradient(white, transparent 28px, transparent calc(100% - 28px), white),
    linear-gradient(to right, white, transparent 28px, transparent calc(100% - 28px), white);
  -webkit-mask-composite: source-over;
  mask-image:
    linear-gradient(white, transparent 28px, transparent calc(100% - 28px), white),
    linear-gradient(to right, white, transparent 28px, transparent calc(100% - 28px), white);
  mask-composite: add;
  pointer-events: none;
  z-index: 1;
  will-change: opacity, filter;
  opacity: calc(var(--beam-opacity-${e}) * ${S} * var(--beam-inner-opacity, 1) * var(--beam-strength, 1));
  ${O}
}

[data-beam="${e}"] [data-beam-bloom] {
  display: none;
  position: absolute;
  inset: 0;
  border-radius: ${t}px;
  clip-path: inset(0 round ${t}px);
  background: ${h};
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  padding: ${o}px;
  pointer-events: none;
  z-index: 3;
  will-change: opacity;
  opacity: 0;
}

[data-beam="${e}"][data-active] [data-beam-bloom],
[data-beam="${e}"][data-fading] [data-beam-bloom] {
  display: block;
  opacity: calc(var(--beam-opacity-${e}) * ${k} * var(--beam-bloom-opacity, 1) * var(--beam-strength, 1));
  ${m}
}

@keyframes beam-fade-in-${e} { to { --beam-opacity-${e}: 1; } }
@keyframes beam-fade-out-${e} { from { --beam-opacity-${e}: 1; } to { --beam-opacity-${e}: 0; } }
${re(e)}

@media (prefers-reduced-motion: reduce) {
  [data-beam="${e}"][data-active],
  [data-beam="${e}"][data-fading],
  [data-beam="${e}"][data-active]::after,
  [data-beam="${e}"][data-fading]::after,
  [data-beam="${e}"][data-active]::before,
  [data-beam="${e}"][data-fading]::before,
  [data-beam="${e}"][data-active] [data-beam-bloom],
  [data-beam="${e}"][data-fading] [data-beam-bloom] {
    animation: none !important;
  }
}
`}function It(a){let{id:e,borderRadius:t,duration:o,strokeOpacity:r,innerOpacity:n,bloomOpacity:s,colorVariant:i,staticColors:l,brightness:d,saturation:g,hueRange:c,theme:b,hairlineOpacity:p=0}=a,x=b==="dark",u=i==="mono"?.5:1,z=(r*u).toFixed(2),S=(n*u).toFixed(2),k=(s*u).toFixed(2),w=x?"70, 70, 70":"0, 0, 0",M=p.toFixed(2),y=`linear-gradient(rgba(${w}, ${M}), rgba(${w}, ${M}))`,{op:v}=ye("pulse-outside",b,o),O=.95,m=.9,$=x?3:6,f=x?22.5:15,h=d.toFixed(2),W=g.toFixed(2),X=l?`filter: brightness(${h}) saturate(${W});`:`filter: hue-rotate(calc(var(--beam-hue-base, 0deg) + var(--beam-hue-${e}))) brightness(${h}) saturate(${W});`,P=`brightness(var(--beam-glow-brightness, ${h})) saturate(var(--beam-glow-saturate, ${W}))`,B=l?`filter: blur(var(--beam-core-blur, ${$}px)) ${P};`:`filter: blur(var(--beam-core-blur, ${$}px)) hue-rotate(calc(var(--beam-hue-base, 0deg) + var(--beam-hue-${e}))) ${P};`,D=l?`filter: blur(var(--beam-bloom-blur, ${f}px)) ${P};`:`filter: blur(var(--beam-bloom-blur, ${f}px)) hue-rotate(calc(var(--beam-hue-base, 0deg) + var(--beam-hue-${e}))) ${P};`,H=Ee(Ce,i,e),L=Ee(Ce,i,e),C=Te(Pt,i,1-v*.5),R=p>0?`${H},
    ${y}`:H;return`
${Ae(e)}

[data-beam="${e}"] {
  position: relative;
  border-radius: ${t}px;
  overflow: visible;
  isolation: isolate;
}

[data-beam="${e}"][data-active] {
${de(e,"beam-fade-in",.6)}
}

[data-beam="${e}"][data-fading] {
${de(e,"beam-fade-out",.5)}
}
${p>0?`
/* Idle hairline \u2014 painted above the (opaque) child in the inner 1px edge ring so
   it overlaps a standard inset component border exactly. */
[data-beam="${e}"]::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${t}px;
  padding: 1px;
  clip-path: inset(0 round ${t}px);
  background: ${y};
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  pointer-events: none;
  z-index: 2;
}
`:""}
[data-beam="${e}"][data-active]::after,
[data-beam="${e}"][data-fading]::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${t}px;
  padding: 1px;
  clip-path: inset(0 round ${t}px);
  background: ${R};
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  pointer-events: none;
  z-index: 2;
  will-change: opacity, filter;
  opacity: calc(var(--beam-opacity-${e}) * ${z} * var(--beam-stroke-opacity, 1) * var(--beam-strength, 1));
  ${X}
}

[data-beam="${e}"][data-active]::before,
[data-beam="${e}"][data-fading]::before {
  content: "";
  position: absolute;
  inset: -10px;
  z-index: -1;
  border-radius: ${t+10}px;
  background: ${L};
  transform: scale(${O}, ${m});
  pointer-events: none;
  will-change: opacity, filter;
  opacity: calc(var(--beam-opacity-${e}) * ${S} * var(--beam-inner-opacity, 1) * var(--beam-strength, 1));
  ${B}
}

[data-beam="${e}"] [data-beam-bloom] {
  display: none;
  position: absolute;
  inset: -30px;
  z-index: -1;
  border-radius: ${t+30}px;
  background: ${C};
  transform: scale(${O}, ${m});
  pointer-events: none;
  will-change: transform;
  opacity: 0;
}

[data-beam="${e}"][data-active] [data-beam-bloom],
[data-beam="${e}"][data-fading] [data-beam-bloom] {
  display: block;
  opacity: calc(var(--beam-opacity-${e}) * ${k} * var(--beam-bloom-opacity, 1) * var(--beam-strength, 1));
  ${D}
}

@keyframes beam-fade-in-${e} { to { --beam-opacity-${e}: 1; } }
@keyframes beam-fade-out-${e} { from { --beam-opacity-${e}: 1; } to { --beam-opacity-${e}: 0; } }
${re(e)}

@media (prefers-reduced-motion: reduce) {
  [data-beam="${e}"][data-active],
  [data-beam="${e}"][data-fading],
  [data-beam="${e}"][data-active]::after,
  [data-beam="${e}"][data-fading]::after,
  [data-beam="${e}"][data-active]::before,
  [data-beam="${e}"][data-fading]::before,
  [data-beam="${e}"][data-active] [data-beam-bloom],
  [data-beam="${e}"][data-fading] [data-beam-bloom] {
    animation: none !important;
  }
}
`}function Lt(a){let{id:e,borderRadius:t,borderWidth:o,duration:r,strokeOpacity:n,innerOpacity:s,bloomOpacity:i,innerShadow:l,colorVariant:d,staticColors:g,brightness:c,saturation:b,hueRange:p,theme:x}=a,u=Math.max(0,t-o),z=x==="dark",S=n,k=s,w=i,M=g?"":`animation: beam-hue-shift-${e} 12s ease-in-out infinite;`,y=g?"":`animation: beam-hue-shift-bloom-${e} 8s ease-in-out infinite;`,v=g?"":`
@keyframes beam-hue-shift-${e} {
  0% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p}deg)) brightness(${c.toFixed(2)}) saturate(${b.toFixed(2)}); }
  50% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) + ${p}deg)) brightness(${c.toFixed(2)}) saturate(${b.toFixed(2)}); }
  100% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p}deg)) brightness(${c.toFixed(2)}) saturate(${b.toFixed(2)}); }
}

@keyframes beam-hue-shift-bloom-${e} {
  0% { filter: blur(8px) hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p+10}deg)) brightness(${c.toFixed(2)}) saturate(${b.toFixed(2)}); }
  50% { filter: blur(8px) hue-rotate(calc(var(--beam-hue-base, 0deg) + ${p+10}deg)) brightness(${c.toFixed(2)}) saturate(${b.toFixed(2)}); }
  100% { filter: blur(8px) hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p+10}deg)) brightness(${c.toFixed(2)}) saturate(${b.toFixed(2)}); }
}`,O=z?`radial-gradient(
        ellipse calc(24px * var(--beam-w-${e})) calc(28px * var(--beam-h-${e})) at calc(var(--beam-x-${e}) * 100%) calc(100% + 2px),
        rgba(255, 255, 255, 0.38) 0%,
        rgba(255, 255, 255, 0.12) 30%,
        transparent 65%
      )`:`radial-gradient(
        ellipse calc(35px * var(--beam-w-${e})) calc(28px * var(--beam-h-${e})) at calc(var(--beam-x-${e}) * 100%) calc(100% + 2px),
        rgba(0, 0, 0, 0.6) 0%,
        rgba(0, 0, 0, 0.25) 35%,
        transparent 70%
      )`,m=wt(d,z,e),$=Ot(d,e),f=Wt(d,z,e),h=d==="mono"?"filter: blur(6px);":"";return`
@property --beam-x-${e} {
  syntax: "<number>";
  initial-value: 0;
  inherits: true;
}

@property --beam-w-${e} {
  syntax: "<number>";
  initial-value: 1;
  inherits: true;
}

@property --beam-h-${e} {
  syntax: "<number>";
  initial-value: 1;
  inherits: true;
}

@property --beam-spike-${e} {
  syntax: "<number>";
  initial-value: 1;
  inherits: true;
}

@property --beam-spike2-${e} {
  syntax: "<number>";
  initial-value: 1;
  inherits: true;
}

@property --beam-edge-${e} {
  syntax: "<number>";
  initial-value: 1;
  inherits: true;
}

@property --beam-opacity-${e} {
  syntax: "<number>";
  initial-value: 0;
  inherits: true;
}

[data-beam="${e}"] {
  position: relative;
  border-radius: ${t}px;
  overflow: hidden;
}

[data-beam="${e}"][data-active] {
  animation:
    beam-travel-${e} ${r}s linear infinite,
    beam-edge-fade-${e} ${r}s linear infinite,
    beam-breathe-${e} ${(r*1.3).toFixed(1)}s ease-in-out infinite,
    beam-spike-${e} ${(r*1.33).toFixed(1)}s ease-in-out infinite,
    beam-spike2-${e} ${(r*1.7).toFixed(1)}s ease-in-out infinite,
    beam-fade-in-${e} 0.6s ease forwards;
}

[data-beam="${e}"][data-fading] {
  animation:
    beam-travel-${e} ${r}s linear infinite,
    beam-edge-fade-${e} ${r}s linear infinite,
    beam-breathe-${e} ${(r*1.3).toFixed(1)}s ease-in-out infinite,
    beam-spike-${e} ${(r*1.33).toFixed(1)}s ease-in-out infinite,
    beam-spike2-${e} ${(r*1.7).toFixed(1)}s ease-in-out infinite,
    beam-fade-out-${e} 0.5s ease forwards;
}

[data-beam="${e}"][data-active]::after,
[data-beam="${e}"][data-fading]::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${u}px;
  padding: ${o}px;
  clip-path: inset(0 round ${t}px);
  background: ${O}, ${m};
  -webkit-mask:
    radial-gradient(
      ellipse calc(78px * var(--beam-w-${e})) calc(60px * var(--beam-h-${e})) at calc(var(--beam-x-${e}) * 100%) 100%,
      white 0%, rgba(255, 255, 255, 0.5) 45%, transparent 100%
    ),
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  -webkit-mask-composite: source-in, xor;
  mask:
    radial-gradient(
      ellipse calc(78px * var(--beam-w-${e})) calc(60px * var(--beam-h-${e})) at calc(var(--beam-x-${e}) * 100%) 100%,
      white 0%, rgba(255, 255, 255, 0.5) 45%, transparent 100%
    ),
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  mask-composite: intersect, exclude;
  pointer-events: none;
  z-index: 2;
  opacity: calc(var(--beam-opacity-${e}) * var(--beam-edge-${e}) * ${S.toFixed(2)} * var(--beam-stroke-opacity, 1) * var(--beam-strength, 1));
  ${M}
}

[data-beam="${e}"][data-active]::before,
[data-beam="${e}"][data-fading]::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${t}px;
  background: ${$};
  box-shadow: inset 0 0 9px 1px ${l};
  -webkit-mask-image:
    radial-gradient(
      ellipse calc(78px * var(--beam-w-${e})) calc(60px * var(--beam-h-${e})) at calc(var(--beam-x-${e}) * 100%) 100%,
      white 0%, rgba(255, 255, 255, 0.5) 45%, transparent 100%
    ),
    linear-gradient(white, transparent 28px, transparent calc(100% - 28px), white),
    linear-gradient(to right, white, transparent 28px, transparent calc(100% - 28px), white);
  -webkit-mask-composite: source-in, source-over;
  mask-image:
    radial-gradient(
      ellipse calc(78px * var(--beam-w-${e})) calc(60px * var(--beam-h-${e})) at calc(var(--beam-x-${e}) * 100%) 100%,
      white 0%, rgba(255, 255, 255, 0.5) 45%, transparent 100%
    ),
    linear-gradient(white, transparent 28px, transparent calc(100% - 28px), white),
    linear-gradient(to right, white, transparent 28px, transparent calc(100% - 28px), white);
  mask-composite: intersect, add;
  pointer-events: none;
  z-index: 1;
  opacity: calc(var(--beam-opacity-${e}) * var(--beam-edge-${e}) * ${k.toFixed(2)} * var(--beam-inner-opacity, 1) * var(--beam-strength, 1));
  clip-path: inset(0 round ${t}px);
  ${M}
}

[data-beam="${e}"] [data-beam-bloom] {
  display: none;
  position: absolute;
  inset: 0;
  border-radius: ${u}px;
  clip-path: inset(0 round ${t}px);
  padding: 0;
  -webkit-mask: radial-gradient(
    ellipse calc(84px * var(--beam-w-${e})) calc(110px * var(--beam-h-${e})) at calc(var(--beam-x-${e}) * 100%) 100%,
    white 0%, rgba(255, 255, 255, 0.5) 35%, transparent 100%
  );
  -webkit-mask-composite: source-over;
  mask: radial-gradient(
    ellipse calc(84px * var(--beam-w-${e})) calc(110px * var(--beam-h-${e})) at calc(var(--beam-x-${e}) * 100%) 100%,
    white 0%, rgba(255, 255, 255, 0.5) 35%, transparent 100%
  );
  mask-composite: add;
  background: ${f};
  ${h}
  pointer-events: none;
  z-index: 3;
  opacity: 0;
}

[data-beam="${e}"][data-active] [data-beam-bloom],
[data-beam="${e}"][data-fading] [data-beam-bloom] {
  display: block;
  opacity: calc(var(--beam-opacity-${e}) * var(--beam-edge-${e}) * ${w.toFixed(2)} * var(--beam-bloom-opacity, 1) * var(--beam-strength, 1));
  ${y}
}

@keyframes beam-travel-${e} {
  0%   { --beam-x-${e}: 0.06;  --beam-w-${e}: 0.5; }
  10%  { --beam-x-${e}: 0.15;  --beam-w-${e}: 0.8; }
  20%  { --beam-x-${e}: 0.25;  --beam-w-${e}: 1.1; }
  30%  { --beam-x-${e}: 0.35;  --beam-w-${e}: 1.3; }
  40%  { --beam-x-${e}: 0.44;  --beam-w-${e}: 1.45; }
  50%  { --beam-x-${e}: 0.5;   --beam-w-${e}: 1.5; }
  60%  { --beam-x-${e}: 0.56;  --beam-w-${e}: 1.45; }
  70%  { --beam-x-${e}: 0.65;  --beam-w-${e}: 1.3; }
  80%  { --beam-x-${e}: 0.75;  --beam-w-${e}: 1.1; }
  90%  { --beam-x-${e}: 0.85;  --beam-w-${e}: 0.8; }
  100% { --beam-x-${e}: 0.94;  --beam-w-${e}: 0.5; }
}

@keyframes beam-edge-fade-${e} {
  0%    { --beam-edge-${e}: 0; }
  12.5% { --beam-edge-${e}: 0; }
  32.5% { --beam-edge-${e}: 1; }
  67.5% { --beam-edge-${e}: 1; }
  87.5% { --beam-edge-${e}: 0; }
  100%  { --beam-edge-${e}: 0; }
}

@keyframes beam-breathe-${e} {
  0%, 100% { --beam-h-${e}: 0.8; }
  25%      { --beam-h-${e}: 1.25; }
  55%      { --beam-h-${e}: 0.85; }
  80%      { --beam-h-${e}: 1.3; }
}

@keyframes beam-spike-${e} {
  0%   { --beam-spike-${e}: 0.8; }
  25%  { --beam-spike-${e}: 1.3; }
  50%  { --beam-spike-${e}: 0.9; }
  75%  { --beam-spike-${e}: 1.4; }
  100% { --beam-spike-${e}: 0.8; }
}

@keyframes beam-spike2-${e} {
  0%   { --beam-spike2-${e}: 1.2; }
  25%  { --beam-spike2-${e}: 0.7; }
  50%  { --beam-spike2-${e}: 1.4; }
  75%  { --beam-spike2-${e}: 0.8; }
  100% { --beam-spike2-${e}: 1.2; }
}

@keyframes beam-fade-in-${e} {
  to { --beam-opacity-${e}: 1; }
}

@keyframes beam-fade-out-${e} {
  from { --beam-opacity-${e}: 1; }
  to { --beam-opacity-${e}: 0; }
}
${v}
${re(e)}
`}var fe=new Set,ee=null,ve=0,Tt=1e3/30-2,At=Math.PI*2;function _e(a){return(1-Math.cos(At*a))/2}function Ve(a){if(ee=requestAnimationFrame(Ve),a-ve<Tt)return;ve=a;let e=a/1e3;fe.forEach(({el:t,config:o})=>{for(let r of o.oscillators){let n=(e-r.delay)/r.period,s=r.a+(r.b-r.a)*_e(n);t.style.setProperty(r.prop,r.unit==="px"?`${s.toFixed(2)}px`:s.toFixed(4))}if(o.hue){let{prop:r,range:n,period:s,continuous:i}=o.hue,l=i?e/s%1*n:-n+2*n*_e(e/s);t.style.setProperty(r,`${l.toFixed(2)}deg`)}})}function Gt(){ee==null&&(ve=0,ee=requestAnimationFrame(Ve))}function qt(){fe.size===0&&ee!=null&&(cancelAnimationFrame(ee),ee=null)}function Ne(a,e){let t={el:a,config:e};return fe.add(t),Gt(),()=>{fe.delete(t),qt()}}var je=window.React;function Ke(a,e,t){return je.createElement(a,t===void 0?e:{...e,key:t})}var Ue=je.Fragment,ae=Ke,ze=Ke;function _t(){let[a,e]=A(()=>typeof window>"u"||window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");return I(()=>{if(typeof window>"u")return;let t=window.matchMedia("(prefers-color-scheme: dark)"),o=r=>{e(r.matches?"dark":"light")};return t.addEventListener("change",o),()=>t.removeEventListener("change",o)},[]),a}function Vt(a,e){return a==="auto"?e:a}var ke=Be(function({children:e,size:t="md",colorVariant:o="colorful",theme:r="dark",staticColors:n=!1,duration:s,active:i=!0,borderRadius:l,brightness:d,saturation:g,hueRange:c=30,strength:b=1,className:p,style:x,onActivate:u,onDeactivate:z,onAnimationEnd:S,...k},w){let y=De().replace(/:/g,"-"),v=_t(),O=le(null),[m,$]=A(i),[f,h]=A(!1),[W,X]=A(!0),[P,B]=A(null),[D,H]=A({x:1,y:1});I(()=>{if(l!=null)return;let Y=O.current;if(!Y)return;let T=()=>{let Z=Y.firstElementChild;if(!Z)return;let ge=getComputedStyle(Z),J=parseFloat(ge.borderTopLeftRadius);!isNaN(J)&&J>0&&B(J)};T();let Q=new MutationObserver(T);return Q.observe(Y,{childList:!0,subtree:!1}),()=>Q.disconnect()},[l,e]),I(()=>{i&&!m&&!f?$(!0):!i&&m&&!f&&h(!0)},[i,m,f]),I(()=>{let Y=O.current;if(!Y||typeof IntersectionObserver>"u")return;let T=new IntersectionObserver(Q=>{for(let Z of Q)X(Z.isIntersecting)},{rootMargin:"256px"});return T.observe(Y),()=>T.disconnect()},[]),I(()=>{if(t!=="pulse-outside"){H({x:1,y:1});return}let Y=O.current;if(!Y)return;let T=350,Q=140,Z=.35,ge=4,J=ie=>Math.max(Z,Math.min(ge,ie)),Re=()=>{let ie=Y.firstElementChild;if(!ie)return;let ce=ie.getBoundingClientRect();if(!ce.width||!ce.height)return;let Ye=+J(ce.width/T).toFixed(3),Xe=+J(ce.height/Q).toFixed(3);H(ue=>ue.x===Ye&&ue.y===Xe?ue:{x:Ye,y:Xe})};if(Re(),typeof ResizeObserver>"u")return;let He=Y.firstElementChild;if(!He)return;let Pe=new ResizeObserver(Re);return Pe.observe(He),()=>Pe.disconnect()},[t,e]);let L=he(Y=>{let T=Y.animationName;T.includes("fade-out")?($(!1),h(!1),z?.()):T.includes("fade-in")&&u?.(),S?.(Y)},[u,z,S]),C=Vt(r,v),R=be[t][C],F=Fe[t],te=t==="pulse-inner"||t==="pulse-outside",oe=l??P??F.borderRadius,N=s??(t==="line"?3.1:te?2.3:1.96),U=g??R.saturation,We=d??R.brightness??1.3,ne=t==="line"?Math.min(c,13):c,se=o==="mono"?!0:n,gt=xe(()=>qe({id:y,borderRadius:oe,borderWidth:F.borderWidth,duration:N,strokeOpacity:R.strokeOpacity,innerOpacity:R.innerOpacity,bloomOpacity:R.bloomOpacity,innerShadow:R.innerShadow,size:t,colorVariant:o,staticColors:se,brightness:We,saturation:U,hueRange:ne,theme:C,hairlineOpacity:R.hairlineOpacity}),[y,oe,F.borderWidth,N,R.strokeOpacity,R.innerOpacity,R.bloomOpacity,R.innerShadow,R.hairlineOpacity,t,o,se,We,U,ne,C]),me=xe(()=>te?Ge(t,C,N,ne,se,y):null,[te,t,C,N,ne,se,y]);I(()=>{if(!me||!(m||f)||!W)return;let Y=O.current;if(Y&&!(typeof window<"u"&&window.matchMedia?.("(prefers-reduced-motion: reduce)").matches))return Ne(Y,me)},[me,m,f,W]);let ut=he(Y=>{O.current=Y,typeof w=="function"?w(Y):w&&(w.current=Y)},[w]),ht={...x??{},"--beam-strength":Math.max(0,Math.min(1,b)),...t==="pulse-outside"?{"--pulse-glow-sx":D.x,"--pulse-glow-sy":D.y}:{}};return ze(Ue,{children:[ae("style",{children:gt}),ze("div",{...k,ref:ut,"data-beam":y,"data-active":m&&!f?"":void 0,"data-fading":f?"":void 0,"data-paused":m&&!f&&!W?"":void 0,className:p,style:ht,onAnimationEnd:L,children:[e,ae("div",{"data-beam-bloom":!0})]})]})});function q(a,e){let t=Math.sin(a*12.9898+e*78.233)*43758.5453;return t-Math.floor(t)}function Qe(a,e){let t=Math.PI*(3-Math.sqrt(5)),o=1-2*(a+.5)/e,r=Math.sqrt(1-o*o),n=a*t;return[r*Math.cos(n),o,r*Math.sin(n)]}function Ze(a,e){return Math.atan2(Math.sin(a-e),Math.cos(a-e))}function _(a,e,t,o,r){let n=Math.sin(e),s=Math.cos(e),i=Math.sin(a),l=Math.cos(a);return(d,g,c)=>{let b=d*l+c*i,p=-d*i+c*l,x=g*s-p*n,u=g*n+p*s;return[t+b*r,o-x*r,u]}}function G(a,e,t,o=.3){e.sort((r,n)=>r.z-n.z);for(let r of e){let n=r.a??1;if(n<.02)continue;let s=Math.min(1,Math.max(0,r.white)),i=Math.round((t?1-s:s)*255);a.fillStyle=`rgba(${i},${i},${i},${n})`,a.beginPath(),a.arc(r.x,r.y,Math.max(o,r.r),0,Math.PI*2),a.fill()}}function V(a,e){return(a/300)**e}function Nt(a,e,t,o){let r=2*e*t+o,n=a%r,s=new Array(e).fill(0),i=-1;if(n<2*e*t){let l=Math.floor(n/t),d=(n-l*t)/t,c=1-(1-Math.min(1,d/.7))**3;if(l<e){for(let b=0;b<l;b++)s[b]=1;s[l]=c,i=l}else{let b=2*e-1-l;for(let p=0;p<b;p++)s[p]=1;s[b]=1-c,i=b}}return{amount:s,active:i}}function jt(a,e,t){let[o,r,n]=a,s=!1;for(let i=0;i<e.length;i++){if(t.amount[i]<=0)continue;let l=e[i],d=l.axis===0?o:l.axis===1?r:n;if(d<l.lo||d>=l.hi)continue;i===t.active&&(s=!0);let g=l.ang*t.amount[i],c=Math.cos(g),b=Math.sin(g);if(l.axis===0){let p=r*c-n*b;n=r*b+n*c,r=p}else if(l.axis===1){let p=o*c+n*b;n=-o*b+n*c,o=p}else{let p=o*c-r*b;r=o*b+r*c,o=p}}return[o,r,n,s]}function Kt(a){let e=[];for(let t=0;t<a;t++){let o=Math.min(2,Math.floor(q(t,2.3)*3)),r=-1+.5*Math.min(3,Math.floor(q(t,5.9)*4)),n=q(t,7.7)<.5?1:-1;e.push({axis:o,lo:r,hi:r+.5,ang:n*Math.PI/2})}return e}var Je=(a,e,t,o,r)=>{let s=e/2,i=e/2,l=e/2*.82,d=.4+.06*Math.sin(t*.35),g=_(t*.5,d,s,i,l),c=t*(.5+(1.7-.5)*(r.scanMul??1)),b=V(e,r.rsPow??.6),p=r.dimBase??1,x=[],u=r.latRings??17,z=r.lonDensity??44;for(let S=0;S<=u;S++){let k=-Math.PI/2+S/u*Math.PI,w=Math.cos(k),M=Math.sin(k),y=Math.max(1,Math.round(Math.abs(w)*z));for(let v=0;v<y;v++){let O=v/y*2*Math.PI,[m,$,f]=g(w*Math.cos(O),M,w*Math.sin(O)),h=(f+1)/2,W=Ze(O+t*.5,c),X=Math.exp(-(W*W)/.18)*Math.max(0,f);x.push({x:m,y:$,z:f,r:((r.rBase??.6)+(r.rDepth??1.7)*h+(r.rBoost??1)*X)*b,white:(r.inkFar??.62)-(r.inkSpan??.54)*h,a:p+(1-p)*Math.min(1,X)})}}G(a,x,o,r.rMin)},et=(a,e,t,o,r)=>{let n=e/2,s=e/2,i=e/2*.82,l=_(t*.55,.35+.1*Math.sin(t*.9),n,s,i),d=V(e,r.rsPow??.6),g=r.moveCount??14,c=Kt(g),b=Nt(t,g,.42,1.2),p=[],x=r.latRings??15,u=r.lonDensity??40;for(let z=0;z<=x;z++){let S=-Math.PI/2+z/x*Math.PI,k=Math.cos(S),w=Math.sin(S),M=Math.max(1,Math.round(Math.abs(k)*u));for(let y=0;y<M;y++){let v=y/M*2*Math.PI,[O,m,$,f]=jt([k*Math.cos(v),w,k*Math.sin(v)],c,b),[h,W,X]=l(O,m,$),P=(X+1)/2;p.push({x:h,y:W,z:X,r:((r.rBase??.6)+(r.rDepth??1.7)*P+(f?r.rActive??.3:0))*d,white:(r.inkFar??.62)-(r.inkSpan??.54)*P-(f?.14:0)})}}G(a,p,o,r.rMin)},tt=(a,e,t,o,r)=>{let n=e/2,s=e/2,i=e/2*.874,l=_(t*.18,.38,n,s,1),d=V(e,r.rsPow??.6),g=[],c=r.rings??15,b=r.lonDensity??40;for(let p=0;p<=c;p++){let x=-Math.PI/2+p/c*Math.PI,u=Math.cos(x),z=Math.sin(x),S=.62*Math.sin(t*2.1-p*.52)+.38*Math.sin(t*1.27+p*.83),k=i*(.88+.105*S),w=Math.max(1,Math.round(Math.abs(u)*b));for(let M=0;M<w;M++){let y=M/w*2*Math.PI,[v,O,m]=l(u*Math.cos(y)*k,z*k,u*Math.sin(y)*k),$=(m/i+1)/2,f=Math.max(0,S);g.push({x:v,y:O,z:m,r:((r.rBase??.6)+(r.rDepth??1.7)*$)*(1+.4*f)*d,white:.66-.56*$-.1*f})}}G(a,g,o,r.rMin)};function Ut(a){return a*a*(3-2*a)}function rt(a){let e=a.length,t=[],o=0;for(let r=0;r<e;r++){let n=a[r],s=a[(r+1)%e],i=Math.hypot(s[0]-n[0],s[1]-n[1]);t.push(i),o+=i}return r=>{let n=r*o,s=0;for(;n>t[s]&&s<e-1;)n-=t[s],s++;let i=a[s],l=a[(s+1)%e],d=t[s]?Math.min(1,n/t[s]):0;return[i[0]+(l[0]-i[0])*d,i[1]+(l[1]-i[1])*d]}}var Qt=a=>{let e=-Math.PI/2+a*2*Math.PI;return[Math.cos(e)*.24,Math.sin(e)*.24]},Zt=rt([[0,-.26],[.24,.16],[-.24,.16]]),Jt=rt([[0,-.2],[.2,-.2],[.2,.2],[-.2,.2],[-.2,-.2]]),we=[Qt,Zt,Jt];function er(a){return Math.max(6,Math.round(34*a))}var Oe=1.4,at=.9,Me=Oe+at,ot=(a,e,t,o,r)=>{let n=we.length,s=t%(Me*n),i=Math.floor(s/Me),l=s-i*Me,d=l>Oe?Ut((l-Oe)/at):0,g=r.spread??1,c=we[i],b=we[(i+1)%n],p=160,x=[];for(let m=0;m<p;m++){let $=m/p,f=c($),h=b($);x.push([(f[0]+(h[0]-f[0])*d)*g,(f[1]+(h[1]-f[1])*d)*g])}let u=[],z=0;for(let m=0;m<p;m++){let $=x[m],f=x[(m+1)%p],h=Math.hypot(f[0]-$[0],f[1]-$[1]);u.push(h),z+=h}let S=er(r.iconD??1),k=(r.rDot??.021)*1.35*g,w=1+.02*Math.sin(l*3.1),M=[],y=e/2,v=0,O=0;for(let m=0;m<S;m++){let $=m/S*z;for(;O+u[v]<$&&v<p-1;)O+=u[v],v++;let f=x[v],h=x[(v+1)%p],W=u[v]?Math.min(1,($-O)/u[v]):0,X=(f[0]+(h[0]-f[0])*W)*w,P=(f[1]+(h[1]-f[1])*W)*w;M.push({x:y+X*e,y:y+P*e,z:0,r:Math.max(.35,k*e),white:.1})}G(a,M,o,r.rMin)};var nt=(a,e,t,o,r)=>{let n=e/2,s=e/2,i=e/2*.82,l=_(t*.12,.3,n,s,1),d=V(e,r.rsPow??.6),g=[],c=r.orbitN??12,b=r.ghostN??40,p=r.particles??3;for(let x=0;x<c;x++){let u=q(x,1.7),z=q(x,5.2),S=q(x,8.9),k=i*(.45+.52*u),w=u*2*Math.PI,M=Math.acos(2*z-1),y=Math.sin(M)*Math.cos(w),v=Math.cos(M),O=Math.sin(M)*Math.sin(w),m=-v,$=y,f=0,h=Math.max(1e-6,Math.sqrt(m*m+$*$));m/=h,$/=h;let W=v*f-O*$,X=O*m-y*f,P=y*$-v*m,B=(.25+.55*S)*(S>.5?1:-1);for(let D=0;D<b;D++){let H=D/b*2*Math.PI,[L,C,R]=l((m*Math.cos(H)+W*Math.sin(H))*k,($*Math.cos(H)+X*Math.sin(H))*k,(f*Math.cos(H)+P*Math.sin(H))*k),F=(R/k+1)/2;g.push({x:L,y:C,z:R,r:(r.ghostR??.9)*d,white:.72,a:(r.ghostA??.5)*(.4+.6*F)})}for(let D=0;D<p;D++){let H=t*B+D/p*2*Math.PI+z*6,[L,C,R]=l((m*Math.cos(H)+W*Math.sin(H))*k,($*Math.cos(H)+X*Math.sin(H))*k,(f*Math.cos(H)+P*Math.sin(H))*k),F=(R/k+1)/2;g.push({x:L,y:C,z:R,r:((r.partR??1.2)+(r.partRDepth??1.6)*F)*d,white:.3-.22*F})}}G(a,g,o,r.rMin)};var st=(a,e,t,o,r)=>{let n=e/2,s=e/2,i=e/2*.78,l=r.spin??1,d=_(t*.1*l,.3,n,s,1),g=V(e,r.rsPow??.6),c=[],b=r.ghostN??150;for(let h=0;h<b;h++){let W=Qe(h,b),[X,P,B]=d(W[0]*i,W[1]*i,W[2]*i),D=(B/i+1)/2;c.push({x:X,y:P,z:B,r:.8*g,white:.78,a:.1+.22*D})}let p=t*.24*l,x=.55+.3*Math.sin(t*.18)*l,u=Math.cos(p),z=0,S=Math.sin(p),k=-S*Math.sin(x),w=Math.cos(x),M=u*Math.sin(x),y=z*M-S*w,v=S*k-u*M,O=u*w-z*k,m=r.lanes??5,$=r.segs??88,f=Math.max(1,Math.round(m*(r.bandMul??1)));for(let h=0;h<f;h++){let W=(h-(f-1)/2)*.075,X=Math.abs(h-(f-1)/2)/Math.max(1,(f-1)/2);for(let P=0;P<$;P++){let B=P/$*2*Math.PI,D=(.16*Math.sin(B*3-t*1.7+h*.22)+.07*Math.sin(B*5+t*1.1))*(r.wobMul??1),H=W+D,L=u*Math.cos(B)+k*Math.sin(B)+y*H,C=z*Math.cos(B)+w*Math.sin(B)+v*H,R=S*Math.cos(B)+M*Math.sin(B)+O*H,F=Math.sqrt(L*L+C*C+R*R),[te,oe,N]=d(L/F*i,C/F*i,R/F*i),U=(N/i+1)/2;c.push({x:te,y:oe,z:N,r:((r.rBase??1.1)+(r.rDepth??1.7)*U)*(1-.25*X)*g,white:.52-.44*U+.18*X,a:.4+.6*U})}}G(a,c,o,r.rMin)};var it={orbits:nt,globe:Je,rubik:et,wave:tt,ribbon:st,morph:ot};var tr=[["latRings","lonDensity"],["rings","lonDensity"],["lanes","segs"]],rr=["orbitN","ghostN"],ar=["iconD"],or=["rBase","rDepth","rActive","rDot","ghostR","partR","partRDepth"];function ct(a,e){let t={...a},o=new Set,r=Math.sqrt(e);for(let[n,s]of tr){let i=t[n],l=t[s];i!=null&&l!=null&&!o.has(n)&&!o.has(s)&&(t[n]=Math.max(2,Math.round(i*r)),t[s]=Math.max(2,Math.round(l*r)),o.add(n),o.add(s))}for(let n of rr){let s=t[n];s!=null&&!o.has(n)&&(t[n]=Math.max(1,Math.round(s*e)))}for(let n of ar){let s=t[n];s!=null&&(t[n]=Math.max(.02,s*e))}return t}function lt(a,e){let t={...a};for(let o of or){let r=t[o];r!=null&&(t[o]=r*e)}return t.rSizeMul=(t.rSizeMul??1)*e,t}var pt={globe:{latRings:17,lonDensity:44,rBase:.6,rDepth:1.7,rBoost:1,inkFar:.62,inkSpan:.54,rsPow:.6,rMin:.3},orbits:{orbitN:12,ghostN:40,ghostR:.9,ghostA:.5,particles:3,partR:1.2,partRDepth:1.6,rsPow:.6,rMin:.3},rubik:{latRings:15,lonDensity:40,moveCount:14,rBase:.6,rDepth:1.7,rActive:.3,inkFar:.62,inkSpan:.54,rsPow:.6,rMin:.3},wave:{rings:15,lonDensity:40,rBase:.6,rDepth:1.7,rsPow:.6,rMin:.3},ribbon:{lanes:5,segs:88,ghostN:150,rBase:1.1,rDepth:1.7,rsPow:.6,rMin:.3},morph:{rDot:.021,iconD:1,rMin:.25}};var nr={working:"orbits",searching:"globe",solving:"rubik",listening:"wave",composing:"ribbon",shaping:"morph"},sr={orbits:{64:{speed:1.885,count:1,size:1},20:{speed:3.9,count:.238,size:2.4}},globe:{64:{speed:2.015,count:.42,size:1.15,extra:{scanMul:4.08,dimBase:.45}},20:{speed:2.665,count:.105,size:1.75,extra:{scanMul:4.335,dimBase:.45}}},rubik:{64:{speed:1.82,count:.35,size:1.05},20:{speed:1.95,count:.088,size:1.9}},wave:{64:{speed:4.388,count:.341,size:1},20:{speed:3.998,count:.105,size:1.6}},ribbon:{64:{speed:2.34,count:.25,size:.85,extra:{spin:0,bandMul:3.9,wobMul:1}},20:{speed:3.12,count:.051,size:1.073,extra:{spin:0,bandMul:4.94,wobMul:1}}},morph:{64:{speed:2.405,count:.54,size:.395,extra:{spread:1.45}},20:{speed:2.08,count:.53,size:1.011,extra:{spread:1.45}}}},bt=new Map;function dt(a,e){let t=`${a}-${e}`,o=bt.get(t);if(o)return o;let r=nr[a],n=sr[r][e],s={...pt[r]};n.count!==1&&(s=ct(s,n.count)),n.size!==1&&(s=lt(s,n.size)),n.extra&&(s={...s,...n.extra});let i={mode:r,speed:n.speed,opts:s};return bt.set(t,i),i}function ir(a){let e=a;for(;e;){let t=e.getAttribute("data-theme");if(t==="dark")return!0;if(t==="light")return!1;if(e.classList.contains("dark"))return!0;if(e.classList.contains("light"))return!1;e=e.parentElement}return null}function cr(){return typeof matchMedia>"u"||matchMedia("(prefers-color-scheme: dark)").matches}function ft(a,e){let[t,o]=A(!0);return I(()=>{if(a==="dark"){o(!0);return}if(a==="light"){o(!1);return}let r=()=>{let l=ir(e.current);o(l??cr())};r();let n=typeof matchMedia<"u"?matchMedia("(prefers-color-scheme: dark)"):null,s=()=>r();n?.addEventListener("change",s);let i=null;return typeof MutationObserver<"u"&&e.current&&(i=new MutationObserver(r),i.observe(document.documentElement,{attributes:!0,attributeFilter:["class","data-theme"],subtree:!0})),()=>{n?.removeEventListener("change",s),i?.disconnect()}},[a,e]),t}function mt(){let[a,e]=A(!1);return I(()=>{if(typeof matchMedia>"u")return;let t=matchMedia("(prefers-reduced-motion: reduce)");e(t.matches);let o=r=>e(r.matches);return t.addEventListener("change",o),()=>t.removeEventListener("change",o)},[]),a}var lr={working:"Working\u2026",searching:"Searching\u2026",solving:"Solving\u2026",listening:"Listening\u2026",composing:"Composing\u2026",shaping:"Shaping\u2026"};function Se({state:a="working",size:e=64,theme:t="auto",speed:o=1,paused:r=!1,style:n,"aria-label":s,...i}){let l=le(null),d=ft(t,l),g=mt();return I(()=>{let c=l.current;if(!c)return;let b=Math.min(2,typeof devicePixelRatio<"u"&&devicePixelRatio||1);c.width=Math.round(e*b),c.height=Math.round(e*b);let p=c.getContext("2d");if(!p)return;let{mode:x,speed:u,opts:z}=dt(a,e),S=it[x],k=u*o,w=W=>{p.setTransform(b,0,0,b,0,0),p.clearRect(0,0,e,e),S(p,e,W,d,z)};if(g){w(.6);return}let M=0,y=!1,v=()=>{w(performance.now()/1e3*k),y&&(M=requestAnimationFrame(v))},O=()=>{y||r||(y=!0,M=requestAnimationFrame(v))},m=()=>{y=!1,cancelAnimationFrame(M)};w(performance.now()/1e3*k);let $=!0,f=typeof IntersectionObserver<"u"?new IntersectionObserver(([W])=>{$=W.isIntersecting,$&&document.visibilityState!=="hidden"?O():m()}):null;f?.observe(c);let h=()=>{document.visibilityState==="hidden"?m():$&&O()};return document.addEventListener("visibilitychange",h),f||O(),()=>{m(),f?.disconnect(),document.removeEventListener("visibilitychange",h)}},[a,e,d,o,r,g]),ae("canvas",{ref:l,role:"img","aria-label":s??lr[a],style:{width:e,height:e,display:"block",...n},...i})}window.VellumMotion={BorderBeam:ke,ThinkingOrb:Se};})();
