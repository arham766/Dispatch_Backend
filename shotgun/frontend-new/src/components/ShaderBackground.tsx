"use client";

import {
  Shader,
  Circle,
  Dither,
  FlowingGradient,
  Glass,
  SolidColor,
  Tritone,
} from "shaders/react";

export function ShaderBackground() {
  return (
    <div
      className="fixed inset-0 w-screen h-screen"
      style={{ zIndex: 0 }}
    >
      <Shader style={{ width: "100%", height: "100%", display: "block" }}>
        <Circle
          id="idmnayde0qhf56tj00g"
          center={{
            x: 0.5,
            y: 0,
          }}
          radius={2.6}
          softness={0.58}
          visible={false}
        />
        <SolidColor color="#000000" />
        <FlowingGradient
          colorB="#9c9c9c"
          colorC="#a1a1a1"
          colorD="#d4d4d4"
          colorSpace="linear"
          distortion={0.4}
          maskSource="idmnayde0qhf56tj00g"
          seed={67}
        />
        <Glass
          aberration={0}
          center={{
            y: 0.5,
            type: "mouse-position",
            reach: 0.05,
            originX: 0.654,
            originY: 0.49733570159857904,
            momentum: 0.1,
            smoothing: 0.7,
          }}
          edgeSoftness={0.15}
          fresnel={0.15}
          fresnelSoftness={1}
          highlight={0.25}
          highlightSoftness={0.52}
          lightAngle={276}
          refraction={0.86}
          // @ts-expect-error runtime accepts object; lib types only declare string
          shape={{
            type: "crescentSDF",
            radius: 0.55,
            innerRatio: 0.8,
            offset: 0.2,
          }}
          thickness={1}
        />
        <Tritone
          colorA="#000000"
          colorB="#e85d1a"
          colorC="#ffe4a8"
          visible={true}
        />
        <Dither
          colorMode="source"
          pattern="blueNoise"
          pixelSize={2}
          threshold={0.62}
        />
      </Shader>
    </div>
  );
}
