/*
 * Copyright 2015 Google Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package com.google.template.soy.jbcsrc.runtime;


import com.google.template.soy.data.LoggingAdvisingAppendable;
import com.google.template.soy.data.SoyValue;
import com.google.template.soy.data.SoyValueProvider;
import com.google.template.soy.jbcsrc.api.RenderResult;
import java.io.IOException;

/**
 * A special implementation of {@link SoyValueProvider} to use as a shared base class for the {@code
 * jbcsrc} implementations of the generated {@code LetValueNode} and {@code CallParamValueNode}
 * implementations.
 *
 * <p>This class resolves to a {@link SoyValueProvider} and calls {@link
 * SoyValueProvider#renderAndResolve}. If you don't neeed to box as a value provider, use {@link
 * DetachableSoyValueProvider} instead, which resolves to a {@link SoyValue} and calls {@link
 * SoyValue#render}.
 */
public abstract class DetachableSoyValueProviderProvider implements SoyValueProvider {
  protected SoyValueProvider resolvedValueProvider = null;

  @Override
  public final SoyValue resolve() {
    JbcSrcRuntime.awaitProvider(this);
    return resolvedValueProvider.resolve();
  }

  @Override
  public final RenderResult status() {
    if (resolvedValueProvider == null) {
      RenderResult subResult = doResolveDelegate();
      if (!subResult.isDone()) {
        return subResult;
      }
    }
    return resolvedValueProvider.status();
  }

  @Override
  public RenderResult renderAndResolve(LoggingAdvisingAppendable appendable) throws IOException {
    RenderResult result = status();
    // This means we have not made enough progress to even begin delegating, keep calling status()
    // until we have.
    if (resolvedValueProvider == null) {
      return result;
    }
    return resolvedValueProvider.renderAndResolve(appendable);
  }

  /** Overridden by generated subclasses to implement lazy detachable resolution. */
  protected abstract RenderResult doResolveDelegate();
}
